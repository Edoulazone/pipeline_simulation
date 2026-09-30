# Image du pipeline: la même pour les workers et pour les commandes (seed, submit, status)
FROM python:3.12-slim

# Pas de fichiers .pyc, et des logs affichés immédiatement (pas de mémoire tampon)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Les dépendances avant le code: Docker garde cette étape en cache tant que requirements.txt ne change pas
# Modifier le code ne relance pas l'installation
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uniquement le code du pipeline: ni les tests, ni les scripts, ni les données
COPY pipeline/ pipeline/

# Jamais root dans le conteneur: si le traitement d'un fichier malveillant était exploité, l'attaquant n'aurait que les droits de cet utilisateur sans privilèges
RUN useradd --create-home --uid 10001 app
USER app

CMD ["python", "-m", "pipeline.worker"]