@echo off
python.exe client.py --connect "localhost:53" --send-text --timeout 10 --qtype "AAAA" --scramble "3" "11"