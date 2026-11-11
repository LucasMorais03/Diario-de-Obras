"""Ponto de entrada para servidores WSGI (gunicorn, waitress)."""
from diario import create_app

app = create_app()
