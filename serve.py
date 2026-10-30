"""Production WSGI entry point. Run behind an HTTPS reverse proxy."""
import os
os.environ.setdefault('ARI_ENV','production')
from app import app
from waitress import serve
if __name__ == '__main__':
    serve(app,host=os.environ.get('ARI_BIND','127.0.0.1'),port=int(os.environ.get('PORT','5000')))
