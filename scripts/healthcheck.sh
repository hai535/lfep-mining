#!/bin/bash
# Quick post-deploy sanity check for lfep.us
# Validates DNS, CF edge, backend API, and CF round-robin consistency.

set -u

echo "=== DNS ==="
echo -n "  1.1.1.1: "; dig +short @1.1.1.1 lfep.us A | tr '\n' ' '; echo
echo -n "  8.8.8.8: "; dig +short @8.8.8.8 lfep.us A | tr '\n' ' '; echo

echo
echo "=== CF authoritative (rogue parking IP detector) ==="
recs=$(dig @art.ns.cloudflare.com +short lfep.us A)
echo "$recs" | sed 's/^/  /'
if echo "$recs" | grep -qE "54\.149\.79\.189|34\.216\.117\.25"; then
  echo "  ⛔ ROGUE Spaceship parking IP detected at CF DNS — DELETE IT NOW"
fi

echo
echo "=== CF edge response ==="
curl -sI --max-time 5 "https://lfep.us/?_=$(date +%s%N)" | grep -iE "server|cf-ray"

echo
echo "=== Backend API ==="
curl -s --max-time 5 https://lfep.us/api/health | python3 -m json.tool

echo
echo "=== Consistency test (20 requests, expect 20/20 OK) ==="
ok=0; bad=0
for i in $(seq 1 20); do
  if curl -s --max-time 5 "https://lfep.us/?_=$RANDOM" | grep -q '\$LFep'; then
    ok=$((ok+1))
  else
    bad=$((bad+1))
  fi
done
echo "  OK: $ok / 20   parking-or-fail: $bad / 20"
if [ "$bad" -gt 0 ]; then
  echo "  ⚠️  Some requests returned non-LFep content — check CF DNS for rogue A records"
fi
