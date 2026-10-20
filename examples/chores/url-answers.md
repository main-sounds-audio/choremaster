---
id: url-answers
every: 15m
title: A URL stopped answering
do: Check the service behind it.
run: url="${CHECK_URL:-https://example.com}"; code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$url"); [ "$code" = 200 ] || { echo "$url answered HTTP $code"; exit 1; }
---
Fails when CHECK_URL (default https://example.com) does not answer HTTP 200 within ten seconds.
`every: 15m` means it runs on every tick.
