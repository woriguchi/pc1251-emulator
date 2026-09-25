# title: 文字のアニメーション(WAITの例)
# WAIT 6にしておくと、PRINTは止まらずに少しだけ見せて次へ進む。
# 最後のWAITだけの行で、PRINTがENTERを待つ動作に戻る。
10 DIM S$(0)*24
20 WAIT 6
30 FOR I=1 TO 20
40 PRINT S$(0);">"
50 S$(0)=S$(0)+" "
60 NEXT I
70 WAIT:PRINT "GOAL"
80 END
