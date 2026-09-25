"""SHARP SC61860(ESR-H)の命令を1つずつ実行するCPUコア

命令の意味はMAMEの実装(src/devices/cpu/sc61860)を下敷きにし、
資料で扱いが分かれる次の3点は、実機のプログラムの書き方から決めた
(『PC-インタープリタを読む』1.4節)。

* 56h(READ): 1バイト命令。次の番地の1バイトをAに読み、そのバイトは
  命令として残す。MAMEは2バイト命令として(P)に即値を入れる。
* LOOP: (R)を1減らし、桁借りがなければ後ろへ飛ぶ。抜けるときに
  スタックの一番上(回数)を1つ捨てる。MAMEは飛ぶたびに捨てる。
* WAIT n: 6+nサイクル(utz82の表、POPCOMの講座)。MAMEは9+2n。

それ以外のサイクル数はMAMEの値を使う。
"""

A, B, I, J = 2, 3, 0, 1
XL, XH, YL, YH = 4, 5, 6, 7
K, L, M, N = 8, 9, 10, 11
IA, IB, FO, CP = 0x5C, 0x5D, 0x5E, 0x5F  # 入出力バッファ


class Bus:
    """メモリと入出力。PC1251クラスがこれを実装する。"""

    def read(self, a: int) -> int:
        raise NotImplementedError

    def write(self, a: int, v: int) -> None:
        raise NotImplementedError

    def in_a(self) -> int:
        return 0

    def in_b(self) -> int:
        return 0

    def out_a(self, v: int) -> None:
        pass

    def out_b(self, v: int) -> None:
        pass

    def out_c(self, v: int) -> None:
        pass

    def out_f(self, v: int) -> None:
        pass

    def test_bits(self) -> int:
        """TEST命令で見える信号。bit0 512ms, bit1 2ms, bit3 BRK, bit6 RESET, bit7 Xin"""
        return 0


def _bcd_add(dst: int, src: int, carry: int) -> tuple[int, int]:
    lo = (dst & 0x0F) + (src & 0x0F) + carry
    c = 0
    if lo > 9:
        lo -= 10
        c = 1
    hi = (dst >> 4) + (src >> 4) + c
    c = 0
    if hi > 9:
        hi -= 10
        c = 1
    return ((hi << 4) | lo) & 0xFF, c


def _bcd_sub(dst: int, src: int, borrow: int) -> tuple[int, int]:
    lo = (dst & 0x0F) - (src & 0x0F) - borrow
    c = 0
    if lo < 0:
        lo += 10
        c = 1
    hi = (dst >> 4) - (src >> 4) - c
    c = 0
    if hi < 0:
        hi += 10
        c = 1
    return ((hi << 4) | lo) & 0xFF, c


class SC61860:
    def __init__(self, bus: Bus):
        self.bus = bus
        self.ram = bytearray(0x80)  # 内部RAM(96バイト+Pが指せる残り)
        self.reset()
        self._ops = [self._build(op) for op in range(256)]

    def reset(self) -> None:
        self.pc = 0
        self.dp = 0
        self.p = self.q = self.r = 0
        self.c = self.z = 0
        self.h = 0  # PTCで積む件数
        self.cycles = 0

    # ---- 補助 ----
    def _fetch(self) -> int:
        v = self.bus.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def _fetch16(self) -> int:
        hi = self._fetch()
        return (hi << 8) | self._fetch()

    def push(self, v: int) -> None:
        self.r = (self.r - 1) & 0x7F
        self.ram[self.r] = v & 0xFF

    def pop(self) -> int:
        v = self.ram[self.r]
        self.r = (self.r + 1) & 0x7F
        return v

    def step(self) -> int:
        """1命令を実行して、かかったサイクル数を返す"""
        op = self._fetch()
        n = self._ops[op]()
        self.cycles += n
        return n

    def run(self, cycles: int) -> int:
        """指定サイクルぶん実行する。実際に使ったサイクル数を返す。"""
        # cyclesは命令ごとに進める。ポートへの書き込み(ブザーの音など)の時刻を
        # 周辺側がcyclesで読むので、まとめて足すと同じ時刻に潰れてしまう
        ops = self._ops
        fetch = self._fetch
        start = self.cycles
        end = start + cycles
        while self.cycles < end:
            self.cycles += ops[fetch()]()
        return self.cycles - start

    # ---- 命令表 ----
    def _build(self, op: int):  # noqa: C901 (命令表は長くなる)
        s = self
        ram = s.ram
        bus = s.bus
        rd, wr = bus.read, bus.write

        if 0x80 <= op <= 0xBF:  # LP l
            v = op & 0x3F

            def f():
                s.p = v
                return 2

            return f
        if op >= 0xE0:  # CAL ln
            hi = (op & 0x1F) << 8

            def f():
                a = hi | s._fetch()
                s.push(s.pc >> 8)
                s.push(s.pc & 0xFF)
                s.pc = a
                return 7

            return f

        def imm(reg):
            def f():
                ram[reg] = s._fetch()
                return 4

            return f

        def incdec_ptr(lo, d, mode):
            hi = lo + 1

            def f():
                v = ram[lo] + d
                ram[lo] = v & 0xFF
                if v > 0xFF or v < 0:
                    ram[hi] = (ram[hi] + d) & 0xFF
                s.dp = ram[lo] | (ram[hi] << 8)
                s.q = hi
                if mode == 0:
                    return 6
                if mode == 1:
                    ram[A] = rd(s.dp)
                else:
                    wr(s.dp, ram[A])
                return 7

            return f

        def inc(reg):
            def f():
                v = (ram[reg] + 1) & 0xFF
                ram[reg] = v
                s.q = reg
                s.z = int(v == 0)
                s.c = int(v == 0)
                return 4

            return f

        def dec(reg):
            def f():
                v = (ram[reg] - 1) & 0xFF
                ram[reg] = v
                s.q = reg
                s.z = int(v == 0)
                s.c = int(v == 0xFF)
                return 4

            return f

        def jr(cond, plus):
            def f():
                base = s.pc
                n = s._fetch()
                if cond():
                    s.pc = (base + n if plus else base - n) & 0xFFFF
                    return 7
                return 4

            return f

        def jp(cond):
            def f():
                a = s._fetch16()
                if cond():
                    s.pc = a
                return 6

            return f

        always = lambda: True  # noqa: E731
        is_z = lambda: s.z  # noqa: E731
        nz = lambda: not s.z  # noqa: E731
        is_c = lambda: s.c  # noqa: E731
        nc = lambda: not s.c  # noqa: E731

        def copy(lenreg):
            def f():
                n = ram[lenreg]
                for _ in range(n + 1):
                    ram[s.p] = ram[s.q]
                    s.p = (s.p + 1) & 0x7F
                    s.q = (s.q + 1) & 0x7F
                return 5 + 2 * n

            return f

        def exch(lenreg):
            def f():
                n = ram[lenreg]
                for _ in range(n + 1):
                    ram[s.p], ram[s.q] = ram[s.q], ram[s.p]
                    s.p = (s.p + 1) & 0x7F
                    s.q = (s.q + 1) & 0x7F
                return 6 + 3 * n

            return f

        def copy_ext(lenreg):
            def f():
                n = ram[lenreg]
                for i in range(n + 1):
                    ram[s.p] = rd(s.dp)
                    s.p = (s.p + 1) & 0x7F
                    if i != n:
                        s.dp = (s.dp + 1) & 0xFFFF
                return 5 + 4 * n

            return f

        def exch_ext(lenreg):
            def f():
                n = ram[lenreg]
                for i in range(n + 1):
                    t = ram[s.p]
                    ram[s.p] = rd(s.dp)
                    wr(s.dp, t)
                    s.p = (s.p + 1) & 0x7F
                    if i != n:
                        s.dp = (s.dp + 1) & 0xFFFF
                return 7 + 6 * n

            return f

        def bcd_a(sub):
            def f():
                n = ram[I]
                src = ram[A]
                c = 0
                zero = 1
                for _ in range(n + 1):
                    if sub:
                        v, c = _bcd_sub(ram[s.p], src, c)
                    else:
                        v, c = _bcd_add(ram[s.p], src, c)
                    ram[s.p] = v
                    if v:
                        zero = 0
                    s.p = (s.p - 1) & 0x7F
                    src = 0
                s.c, s.z = c, zero
                return 7 + 3 * n

            return f

        def bcd_q(sub):
            def f():
                n = ram[I]
                c = 0
                zero = 1
                for _ in range(n + 1):
                    if sub:
                        v, c = _bcd_sub(ram[s.p], ram[s.q], c)
                    else:
                        v, c = _bcd_add(ram[s.p], ram[s.q], c)
                    ram[s.p] = v
                    if v:
                        zero = 0
                    s.p = (s.p - 1) & 0x7F
                    s.q = (s.q - 1) & 0x7F
                s.q = (s.q - 1) & 0x7F
                s.c, s.z = c, zero
                return 7 + 3 * n

            return f

        def add_to(reg_fn, val_fn, carry=False, sub=False, cyc=3):
            def f():
                a = reg_fn()
                v = val_fn()
                if sub:
                    t = ram[a] - v - (s.c if carry else 0)
                    s.c = int(t < 0)
                else:
                    t = ram[a] + v + (s.c if carry else 0)
                    s.c = int(t > 0xFF)
                t &= 0xFF
                ram[a] = t
                s.z = int(t == 0)
                return cyc

            return f

        def logic(reg_fn, val_fn, kind, cyc):
            def f():
                a = reg_fn()
                v = val_fn()
                if kind == "and":
                    t = ram[a] & v
                    ram[a] = t
                elif kind == "or":
                    t = ram[a] | v
                    ram[a] = t
                else:  # test
                    t = ram[a] & v
                s.z = int(t == 0)
                return cyc

            return f

        def cmp(reg_fn, val_fn, cyc):
            def f():
                t = ram[reg_fn()] - val_fn()
                s.z = int(t == 0)
                s.c = int(t < 0)
                return cyc

            return f

        P = lambda: s.p  # noqa: E731
        RA = lambda: A  # noqa: E731
        IMM = s._fetch
        VA = lambda: ram[A]  # noqa: E731

        def ext_logic(kind):
            def f():
                n = s._fetch()
                v = rd(s.dp)
                if kind == "and":
                    v &= n
                    wr(s.dp, v)
                elif kind == "or":
                    v |= n
                    wr(s.dp, v)
                else:
                    v &= n
                s.z = int(v == 0)
                return 6

            return f

        def simple(fn, cyc):
            def f():
                fn()
                return cyc

            return f

        def g_ldp():
            ram[A] = s.p

        def g_ldq():
            ram[A] = s.q

        def g_ldr():
            ram[A] = s.r

        def g_stp():
            s.p = ram[A] & 0x7F

        def g_stq():
            s.q = ram[A] & 0x7F

        def g_str():
            s.r = ram[A] & 0x7F

        # --- 各オペコード ---
        if op == 0x00:
            return imm(I)
        if op == 0x01:
            return imm(J)
        if op == 0x02:
            return imm(A)
        if op == 0x03:
            return imm(B)
        if op == 0x04:
            return incdec_ptr(XL, 1, 0)
        if op == 0x05:
            return incdec_ptr(XL, -1, 0)
        if op == 0x06:
            return incdec_ptr(YL, 1, 0)
        if op == 0x07:
            return incdec_ptr(YL, -1, 0)
        if op == 0x08:
            return copy(I)
        if op == 0x09:
            return exch(I)
        if op == 0x0A:
            return copy(J)
        if op == 0x0B:
            return exch(J)
        if op == 0x0C:
            return bcd_a(False)
        if op == 0x0D:
            return bcd_a(True)
        if op == 0x0E:
            return bcd_q(False)
        if op == 0x0F:
            return bcd_q(True)
        if op == 0x10:  # LIDP nm

            def f():
                s.dp = s._fetch16()
                return 8

            return f
        if op == 0x11:  # LIDL n

            def f():
                s.dp = (s.dp & 0xFF00) | s._fetch()
                return 5

            return f
        if op == 0x12:  # LIP n

            def f():
                s.p = s._fetch() & 0x7F
                return 4

            return f
        if op == 0x13:  # LIQ n

            def f():
                s.q = s._fetch() & 0x7F
                return 4

            return f
        if op in (0x14, 0x15):  # ADB / SBB
            sub = op == 0x15

            def f():
                p0 = s.p
                p1 = (p0 + 1) & 0x7F
                if sub:
                    t = ram[p0] - ram[A]
                    t2 = ram[p1] - ram[B] - (1 if t < 0 else 0)
                    s.c = int(t2 < 0)
                else:
                    t = ram[p0] + ram[A]
                    t2 = ram[p1] + ram[B] + (1 if t > 0xFF else 0)
                    s.c = int(t2 > 0xFF)
                ram[p0] = t & 0xFF
                ram[p1] = t2 & 0xFF
                s.z = int(ram[p0] == 0 and ram[p1] == 0)
                s.p = p1
                return 5

            return f
        if op == 0x18:
            return copy_ext(I)
        if op == 0x19:
            return exch_ext(I)
        if op == 0x1A:
            return copy_ext(J)
        if op == 0x1B:
            return exch_ext(J)
        if op == 0x1C:  # SRW

            def f():
                n = ram[I]
                t = 0
                for _ in range(n + 1):
                    t |= ram[s.p]
                    ram[s.p] = (t >> 4) & 0xFF
                    s.p = (s.p + 1) & 0x7F
                    t = (t << 8) & 0xF00
                return 5 + n

            return f
        if op == 0x1D:  # SLW

            def f():
                n = ram[I]
                t = 0
                for _ in range(n + 1):
                    t |= ram[s.p] << 4
                    ram[s.p] = t & 0xFF
                    s.p = (s.p - 1) & 0x7F
                    t >>= 8
                return 5 + n

            return f
        if op == 0x1E:  # FILM

            def f():
                n = ram[I]
                for _ in range(n + 1):
                    ram[s.p] = ram[A]
                    s.p = (s.p + 1) & 0x7F
                return 5 + n

            return f
        if op == 0x1F:  # FILD

            def f():
                n = ram[I]
                for i in range(n + 1):
                    wr(s.dp, ram[A])
                    if i != n:
                        s.dp = (s.dp + 1) & 0xFFFF
                return 4 + 3 * n

            return f
        if op == 0x20:
            return simple(g_ldp, 2)
        if op == 0x21:
            return simple(g_ldq, 2)
        if op == 0x22:
            return simple(g_ldr, 2)
        if op == 0x23:  # CLRA

            def f():
                ram[A] = 0
                return 2

            return f
        if op == 0x24:
            return incdec_ptr(XL, 1, 1)
        if op == 0x25:
            return incdec_ptr(XL, -1, 1)
        if op == 0x26:
            return incdec_ptr(YL, 1, 2)
        if op == 0x27:
            return incdec_ptr(YL, -1, 2)
        if op == 0x28:
            return jr(nz, True)
        if op == 0x29:
            return jr(nz, False)
        if op == 0x2A:
            return jr(nc, True)
        if op == 0x2B:
            return jr(nc, False)
        if op == 0x2C:
            return jr(always, True)
        if op == 0x2D:
            return jr(always, False)
        if op == 0x2F:  # LOOP n

            def f():
                base = s.pc
                n = s._fetch()
                t = (ram[s.r] - 1) & 0xFF
                ram[s.r] = t
                s.z = int(t == 0)
                s.c = int(t == 0xFF)
                if not s.c:
                    s.pc = (base - n) & 0xFFFF
                    return 10
                s.pop()  # 抜けるときに回数を捨てる
                return 7

            return f
        if op == 0x30:
            return simple(g_stp, 2)
        if op == 0x31:
            return simple(g_stq, 2)
        if op == 0x32:
            return simple(g_str, 2)
        if op == 0x34:  # PUSH

            def f():
                s.push(ram[A])
                return 3

            return f
        if op == 0x35:  # DATA

            def f():
                n = ram[I]
                for i in range(n + 1):
                    ram[s.p] = rd((ram[B] << 8) | ram[A])
                    s.p = (s.p + 1) & 0x7F
                    if i != n:
                        v = ram[A] + 1
                        ram[A] = v & 0xFF
                        if v > 0xFF:
                            ram[B] = (ram[B] + 1) & 0xFF
                return 11 + 4 * n

            return f
        if op == 0x37:  # RTN

            def f():
                lo = s.pop()
                s.pc = lo | (s.pop() << 8)
                return 4

            return f
        if op == 0x38:
            return jr(is_z, True)
        if op == 0x39:
            return jr(is_z, False)
        if op == 0x3A:
            return jr(is_c, True)
        if op == 0x3B:
            return jr(is_c, False)
        if op == 0x40:
            return inc(I)
        if op == 0x41:
            return dec(I)
        if op == 0x42:
            return inc(A)
        if op == 0x43:
            return dec(A)
        if op == 0x44:
            return add_to(P, VA)
        if op == 0x45:
            return add_to(P, VA, sub=True)
        if op == 0x46:
            return logic(P, VA, "and", 3)
        if op == 0x47:
            return logic(P, VA, "or", 3)
        if op == 0x48:
            return inc(K)
        if op == 0x49:
            return dec(K)
        if op == 0x4A:
            return inc(M)
        if op == 0x4B:
            return dec(M)
        if op == 0x4C:  # INA

            def f():
                v = bus.in_a() & 0xFF
                ram[A] = v
                s.z = int(v == 0)
                return 2

            return f
        if op == 0x4D:  # NOPW
            return lambda: 2
        if op == 0x4E:  # WAIT n

            def f():
                return 6 + s._fetch()

            return f
        if op in (0x4F, 0x6F):  # CUP / CDN (Xinの変化を待つ)
            level = 1 if op == 0x6F else 0

            def f():
                n = ram[I]
                cyc = 1
                x = (bus.test_bits() >> 7) & 1
                for _ in range(n + 1):
                    ram[s.p] = (ram[s.p] + 1) & 0x7F
                    cyc += 4
                    x = (bus.test_bits() >> 7) & 1
                    if x != level:
                        break
                s.z = x
                return cyc

            return f
        if op == 0x50:  # INCP

            def f():
                s.p = (s.p + 1) & 0x7F
                return 2

            return f
        if op == 0x51:  # DECP

            def f():
                s.p = (s.p - 1) & 0x7F
                return 2

            return f
        if op == 0x52:  # STD

            def f():
                wr(s.dp, ram[A])
                return 2

            return f
        if op == 0x53:  # MVDM (DP)←(P)

            def f():
                wr(s.dp, ram[s.p])
                return 3

            return f
        if op == 0x54:  # READM (P)←即値

            def f():
                ram[s.p] = s._fetch()
                return 3

            return f
        if op == 0x55:  # MVMD (P)←(DP)

            def f():
                ram[s.p] = rd(s.dp)
                return 3

            return f
        if op == 0x56:  # READ: A←(PC+1)。そのバイトは消費しない

            def f():
                ram[A] = rd(s.pc)
                return 3

            return f
        if op == 0x57:  # LDD

            def f():
                ram[A] = rd(s.dp)
                return 3

            return f
        if op == 0x58:  # SWP

            def f():
                t = ram[A]
                ram[A] = ((t << 4) | (t >> 4)) & 0xFF
                return 2

            return f
        if op == 0x59:  # LDM

            def f():
                ram[A] = ram[s.p]
                return 2

            return f
        if op == 0x5A:  # SL

            def f():
                t = (ram[A] << 1) | s.c
                s.c = t >> 8
                ram[A] = t & 0xFF
                return 2

            return f
        if op == 0x5B:  # POP

            def f():
                ram[A] = s.pop()
                return 2

            return f
        if op == 0x5D:  # OUTA

            def f():
                s.q = IA
                bus.out_a(ram[IA])
                return 3

            return f
        if op == 0x5F:  # OUTF

            def f():
                s.q = FO
                bus.out_f(ram[FO])
                return 3

            return f
        if op == 0x60:
            return logic(P, IMM, "and", 4)
        if op == 0x61:
            return logic(P, IMM, "or", 4)
        if op == 0x62:
            return logic(P, IMM, "test", 4)
        if op == 0x63:
            return cmp(P, IMM, 4)
        if op == 0x64:
            return logic(RA, IMM, "and", 4)
        if op == 0x65:
            return logic(RA, IMM, "or", 4)
        if op == 0x66:
            return logic(RA, IMM, "test", 4)
        if op == 0x67:
            return cmp(RA, IMM, 4)
        if op == 0x69:  # DTC

            def f():
                for _ in range(s.h):
                    v = s._fetch()
                    a = s._fetch16()
                    s.z = int(v == ram[A])
                    if s.z:
                        s.pc = a
                        return 3
                s.pc = s._fetch16()
                return 3

            return f
        if op == 0x6B:  # TEST n

            def f():
                n = s._fetch()
                s.z = int((bus.test_bits() & n) == 0)
                return 4

            return f
        if op == 0x70:
            return add_to(P, IMM, cyc=4)
        if op == 0x71:
            return add_to(P, IMM, sub=True, cyc=4)
        if op == 0x74:
            return add_to(RA, IMM, cyc=4)
        if op == 0x75:
            return add_to(RA, IMM, sub=True, cyc=4)
        if op == 0x78:  # CALL nm

            def f():
                a = s._fetch16()
                s.push(s.pc >> 8)
                s.push(s.pc & 0xFF)
                s.pc = a
                return 8

            return f
        if op == 0x79:
            return jp(always)
        if op == 0x7A:  # PTC h,nm

            def f():
                s.h = s._fetch()
                a = s._fetch16()
                s.push(a >> 8)
                s.push(a & 0xFF)
                return 9

            return f
        if op == 0x7C:
            return jp(nz)
        if op == 0x7D:
            return jp(nc)
        if op == 0x7E:
            return jp(is_z)
        if op == 0x7F:
            return jp(is_c)
        if op == 0xC0:
            return inc(J)
        if op == 0xC1:
            return dec(J)
        if op == 0xC2:
            return inc(B)
        if op == 0xC3:
            return dec(B)
        if op == 0xC4:
            return add_to(P, VA, carry=True)
        if op == 0xC5:
            return add_to(P, VA, carry=True, sub=True)
        if op == 0xC6:  # TSMA (P)&A
            return logic(P, VA, "test", 3)
        if op == 0xC7:
            return cmp(P, VA, 3)
        if op == 0xC8:
            return inc(L)
        if op == 0xC9:
            return dec(L)
        if op == 0xCA:
            return inc(N)
        if op == 0xCB:
            return dec(N)
        if op == 0xCC:  # INB

            def f():
                v = bus.in_b() & 0xFF
                ram[A] = v
                s.z = int(v == 0)
                return 2

            return f
        if op == 0xCE:  # NOPT
            return lambda: 3
        if op == 0xD0:  # SC

            def f():
                s.c = 1
                s.z = 1
                return 2

            return f
        if op == 0xD1:  # RC

            def f():
                s.c = 0
                s.z = 1
                return 2

            return f
        if op == 0xD2:  # SR

            def f():
                t = ram[A] | (s.c << 8)
                s.c = t & 1
                ram[A] = t >> 1
                return 2

            return f
        if op == 0xD4:
            return ext_logic("and")
        if op == 0xD5:
            return ext_logic("or")
        if op == 0xD6:
            return ext_logic("test")
        if op == 0xD8:  # LEAVE

            def f():
                ram[s.r] = 0
                return 2

            return f
        if op == 0xDA:  # EXAB

            def f():
                ram[A], ram[B] = ram[B], ram[A]
                return 3

            return f
        if op == 0xDB:  # EXAM

            def f():
                ram[A], ram[s.p] = ram[s.p], ram[A]
                return 3

            return f
        if op == 0xDD:  # OUTB

            def f():
                s.q = IB
                bus.out_b(ram[IB])
                return 2

            return f
        if op == 0xDF:  # OUTC

            def f():
                s.q = CP
                bus.out_c(ram[CP])
                return 2

            return f
        # 資料に動作の記述がない命令は何もしない
        return lambda: 2
