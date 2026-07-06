```
 Invoke-bash @'
 curl -sS -X POST https://api.relingo.net/api/getUserConfig \
         -H "Content-Type: application/json" \
         -H "x-relingo-token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ODA1MTA4MmYzNTY0N2E1NWMzMGRiYSIsImlhdCI6MTc4MzMyNDMxMiwiZXhwIjoxNzk4ODc2MzEyfQ.l04cHQcqufHqk0Hl7tNhFINxJC-gMxcfo-TiIZiSVAA" \
         -H "x-relingo-lang: zh-CN" \
         -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36" \
         -d '{}'
'@|ConvertFrom-Json|select -ExpandProperty data |select -ExpandProperty config|select -ExpandProperty currentBooks|Group-Object -Property scope|select name,Group|ConvertTo-Json -Depth 10
```
