# Du pipeline local au pipeline distribué

Pipeline batch d'analyse de publications de réseaux sociaux : pour chaque plateforme
et chaque jour, nettoyer les données brutes, extraire les hashtags et les domaines
cités, puis compter les publications qui les mentionnent.

Le projet contient **deux versions** du même pipeline :

- **avant** (`local_pipeline.py`) : un script local, séquentiel, qui écrit un CSV ;
- **après** (`pipeline/`) : des workers identiques qui se partagent le travail, avec un
  stockage objet partagé et une base de données.

Les deux utilisent **la même logique métier** (`pipeline/transform.py`) et produisent
**le même résultat**, vérifié par `scripts/compare_results.py`.

## Architecture de la version distribuée

```
 data/raw ──seed──► Stockage objet (MinIO)      données brutes, jamais modifiées
                      raw/<plateforme>/<jour>.jsonl
                            │
 submit ──► PostgreSQL : table tasks            une tâche par fichier
                            │  SELECT ... FOR UPDATE SKIP LOCKED
               ┌────────────┼────────────┐
           worker 1     worker 2     worker N    identiques, sans état
               └────────────┼────────────┘
                            ▼  une seule transaction :
                               résultat écrit + tâche terminée
             PostgreSQL : table daily_counts     écriture idempotente
```

## Les 8 problèmes de la version locale, et leur correction

| # | Problème | Correction | Où |
|---|---|---|---|
| 1 | Configuration codée en dur | Variables d'environnement, vérifiées au démarrage | `config.py` |
| 2 | Traitement séquentiel | N workers en parallèle (`--scale worker=N`) | `worker.py` |
| 3 | Tout l'historique retraité à chaque fois | Une tâche par fichier, avec un statut | `tasks.py`, `submit.py` |
| 4 | Lecture sur le disque local | Stockage objet compatible S3 | `storage.py` |
| 5 | Statistiques de qualité perdues | Enregistrées avec chaque tâche | `tasks.py` |
| 6 | Tout en mémoire jusqu'à la fin | Chaque fichier écrit dès qu'il est traité | `worker.py` |
| 7 | Écriture non atomique | Remplacement de partition dans une transaction | `sink.py` |
| 8 | Aucune reprise possible | Verrous libérés au crash, essais espacés, statut `failed` | `tasks.py`, `worker.py` |

## Structure

```
pipeline/
  transform.py   logique métier : nettoyer, extraire, agréger (fonctions pures)
  config.py      configuration par variables d'environnement
  storage.py     lecture en flux dans le stockage objet
  sink.py        écriture idempotente des résultats
  tasks.py       file de tâches dans PostgreSQL
  worker.py      le worker
  seed.py / submit.py / status.py   commandes d'exploitation
scripts/
  generate_posts.py     données factices, reproductibles
  compare_results.py    comparaison version locale / version distribuée
sql/schema.sql   tables daily_counts et tasks
local_pipeline.py      version « avant »
demo.sh                démo guidée (voir « Démo guidée » plus bas)
```

## Lancer

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                                  # puis changer les mots de passe
                                                      # (sans caractères spéciaux : ils vont dans une URL)

python scripts/generate_posts.py                      # données factices
python local_pipeline.py                              # version locale → output/daily_counts.csv

docker compose up -d --build                          # MinIO, PostgreSQL, 1 worker
docker compose run --rm cli python -m pipeline.seed
docker compose run --rm cli python -m pipeline.submit
docker compose up -d --scale worker=4
docker compose run --rm cli python -m pipeline.status

set -a && . ./.env && set +a
python scripts/compare_results.py                     # RÉSULTAT : IDENTIQUE
```

## Démo guidée

```bash
source .venv/bin/activate          # compare_results.py tourne sur ta machine
python scripts/generate_posts.py   # si data/raw est vide
python local_pipeline.py           # le CSV de référence pour la comparaison
./demo.sh                          # Entrée entre chaque étape
```

La démo repart de zéro (`docker compose down -v` : base et stockage effacés), puis
montre dans l'ordre : 1 worker, le passage à 4 workers, un worker tué en pleine tâche,
la reprise de sa tâche par un autre, la comparaison avec la version locale et le rejeu
complet (idempotence). Chaque tâche est ralentie de 5 s pour avoir le temps de voir ;
`WORK_S=2 ./demo.sh` pour aller plus vite.

MinIO ne publie plus d'image Docker : `docker-compose.yml` utilise `pgsty/minio`, un
fork communautaire compatible, épinglé sur une version précise.

## Tests

```bash
python -m pytest                  # tests unitaires seulement

set -a && . ./.env && set +a      # tests d'intégration (PostgreSQL démarré)
TEST_DATABASE_URL=$DATABASE_URL python -m pytest
```

Sans `TEST_DATABASE_URL`, les tests qui ont besoin de PostgreSQL sont ignorés.
**Attention** : ces tests suppriment et recréent les tables `tasks` et `daily_counts`.
Les lancer sur la base de la démo efface ses résultats (relancer `./demo.sh` ensuite).

## Limites connues

- **Une seule machine** : Docker Compose simule la distribution. Plusieurs machines :
  Kubernetes, Nomad ou des conteneurs gérés ; le code ne change pas.
- **PostgreSQL est un point unique de défaillance** : en production, réplique et
  bascule automatique.
- **Un worker tué n'incrémente pas son compteur d'essais** : un fichier qui ferait
  planter le processus lui-même serait repris indéfiniment.
- **Une transaction reste ouverte pendant tout le traitement d'un fichier** : adapté à
  des tâches courtes. Pour des tâches longues, un système de bail.
- **Secrets en variables d'environnement** et compte administrateur de MinIO : à
  remplacer par un gestionnaire de secrets et un compte limité en production.
- **Schéma appliqué au premier démarrage** : en production, un outil de migrations.