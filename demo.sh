#!/usr/bin/env bash

# Usage: ./demo.sh

set -euo pipefail

WORK_S=${WORK_S:-5}        # ralentissement de chaque tâche, pour avoir le temps d'agir
CLI="docker compose run --rm cli python -m pipeline"

step()  { printf '\n\033[1;36m=== %s ===\033[0m\n' "$1"; }
say()   { printf '\033[0;90m# %s\033[0m\n' "$1"; }
pause() { read -rp $'\n[Entrée pour continuer] ' _; }
run()   { printf '\033[1;33m$ %s\033[0m\n' "$*"; eval "$@"; }

# Attend que les 21 tâches soient terminées, 3 minutes au plus
wait_all_done() {
  for _ in $(seq 90); do
    $CLI.status 2>/dev/null | grep -qE '^21 tâches : 21 done' && return 0
    sleep 2
  done
  echo "Toutes les tâches ne sont pas terminées : voir « $CLI.status »"; return 1
}

# Charge le .env pour les commandes lancées depuis ta machine
set -a; . ./.env; set +a

step "0. Point de départ : base vide, fichiers bruts déjà dans le stockage objet"
run "docker compose down -v --remove-orphans >/dev/null 2>&1 || true"
run "docker compose build -q"
run "SIMULATED_WORK_S=$WORK_S docker compose up -d --scale worker=0 >/dev/null"
run "$CLI.seed | tail -1"
pause

step "1. Un seul worker"
say "Même logique métier que la version locale, mais le travail est découpé en tâches."
run "SIMULATED_WORK_S=$WORK_S docker compose up -d --scale worker=1 >/dev/null"
run "$CLI.submit"
sleep 3
run "$CLI.status | tail -3"
pause

step "2. Passage à 4 workers, sans changer une ligne de code"
run "SIMULATED_WORK_S=$WORK_S docker compose up -d --scale worker=4 --no-recreate >/dev/null"
sleep 4
run "$CLI.status | grep -E 'running|tâches'"
pause

step "3. Crash : on tue un worker en pleine tâche (SIGKILL, comme une panne)"
VICTIM=$(docker compose ps -q worker | head -1)
VICTIM_ID=${VICTIM:0:12}     # le nom du worker = l'identifiant court du conteneur
say "Worker tué : $VICTIM_ID. Sa dernière tâche :"
run "docker compose logs --no-log-prefix worker | grep '\"$VICTIM_ID\"' | grep tache_prise | tail -1"
run "docker kill $VICTIM >/dev/null"
say "Sa transaction est annulée par PostgreSQL, la tâche redevient disponible."
pause

step "4. Fin du traitement"
say "On attend que toutes les tâches soient terminées..."
wait_all_done
run "$CLI.status | tail -2"
say "Qui a finalement traité la tâche du worker tué :"
TASK=$(docker compose logs --no-log-prefix worker 2>/dev/null | grep "\"$VICTIM_ID\"" \
       | grep tache_prise | tail -1 | grep -oE '"platform": "[^"]+", "day": "[^"]+"')
# « logs » regroupe les lignes par conteneur : sort les remet dans l'ordre chronologique
# (chaque ligne commence par {"ts": "<date ISO>", donc l'ordre alphabétique = l'ordre du temps)
run "docker compose logs --no-log-prefix worker | grep '$TASK' | grep -E 'tache_(prise|terminee)' | sort | cut -c1-150"
pause

step "5. La preuve : même résultat que la version locale, sans doublon"
run "python scripts/compare_results.py"
pause

step "6. Bonus : tout rejouer ne change rien (idempotence)"
run "$CLI.submit --rerun"
wait_all_done
run "python scripts/compare_results.py | tail -1"

step "Fin de la démo"
say "Pour tout arrêter : docker compose down"