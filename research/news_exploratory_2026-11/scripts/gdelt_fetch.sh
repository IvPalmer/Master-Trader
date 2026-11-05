#!/bin/bash
# GDELT DOC 2.0 daily article counts, exploratory window 2017-2022 only (2023+ held out)
cd "$(dirname "$0")/.."
Q_CRASH='(bitcoin%20OR%20crypto%20OR%20cryptocurrency)%20(crash%20OR%20plunge%20OR%20collapse%20OR%20selloff%20OR%20hack%20OR%20bankruptcy)'
Q_BASE='(bitcoin%20OR%20crypto%20OR%20cryptocurrency)'
for y in 2017 2018 2019 2020 2021 2022; do
  for name in crash base; do
    q=$Q_CRASH; [ $name = base ] && q=$Q_BASE
    f=data/gdelt_${name}_$y.json
    for att in 1 2 3; do
      curl -s -m 60 -A "Mozilla/5.0" "https://api.gdeltproject.org/api/v2/doc/doc?query=$q&mode=timelinevolraw&startdatetime=${y}0101000000&enddatetime=${y}1231235959&format=json" -o $f
      python3 -c "import json,sys;json.load(open('$f'))['timeline']" 2>/dev/null && break
      echo "$f attempt $att failed: $(head -c 120 $f)"; sleep 20
    done
    sleep 7
  done
done
echo DONE
