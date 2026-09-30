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
demo.sh / DEMO.md      démo guidée et scénario
```

## Lancer

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                                  # puis changer les mots de passe

python scripts/generate_posts.py                      # données factices
python local_pipeline.py                              # version locale

docker compose up -d --build                          # MinIO, PostgreSQL, 1 worker
docker compose run --rm cli python -m pipeline.seed
docker compose run --rm cli python -m pipeline.submit
docker compose up -d --scale worker=4
docker compose run --rm cli python -m pipeline.status

set -a && . ./.env && set +a
python scripts/compare_results.py                     # RÉSULTAT : IDENTIQUE
```

Démo guidée : `./demo.sh` (voir `DEMO.md`).

## Tests

```bash
set -a && . ./.env && set +a      # pour les tests d'intégration (PostgreSQL démarré)
python -m pytest
```

Sans `TEST_DATABASE_URL`, les tests qui ont besoin de PostgreSQL sont ignorés.

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