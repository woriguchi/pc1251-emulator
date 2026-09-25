# title: 正弦波を流す(マシン語)
# 同じ名前のwave.hexを先に書き込み、CALL &C200で呼ぶ。Escで止まる
10 WAIT 96:PRINT "SC61860 SINE WAVE"
20 CALL &C200
30 END
