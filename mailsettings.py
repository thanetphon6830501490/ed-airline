"""Encrypted local SMTP configuration. No automatic outbound test messages."""
import os,json
from pathlib import Path
import click
def configure_mailsettings(app):
    file=Path(app.config['DATABASE']).parent/'smtp.enc'
    if file.exists():
        settings=json.loads(app.profile_cipher.decrypt(file.read_bytes()))
        for key,value in settings.items():os.environ.setdefault(key,value)
    @app.cli.command('configure-email')
    def configure():
        settings={}
        settings['ARI_SMTP_HOST']=click.prompt('SMTP host').strip()
        settings['ARI_SMTP_PORT']=str(click.prompt('SMTP port',default=587,type=int))
        settings['ARI_SMTP_FROM']=click.prompt('Sender email').strip()
        settings['ARI_SMTP_USER']=click.prompt('SMTP username').strip()
        settings['ARI_SMTP_PASSWORD']=click.prompt('SMTP app password / credential',hide_input=True,confirmation_prompt=True)
        settings['ARI_PUBLIC_URL']=click.prompt('Website URL accessible to recipient',default='http://127.0.0.1:5000').rstrip('/')
        if not settings['ARI_PUBLIC_URL'].startswith(('http://','https://')):raise click.ClickException('Website URL must start with http:// or https://')
        temporary=file.with_suffix('.tmp');temporary.write_bytes(app.profile_cipher.encrypt(json.dumps(settings).encode()));temporary.replace(file)
        click.echo('Saved encrypted SMTP settings. Restart the website. No email has been sent.')
    @app.cli.command('email-status')
    def status():
        ready=all(os.environ.get(k) for k in ('ARI_SMTP_HOST','ARI_SMTP_FROM','ARI_SMTP_USER','ARI_SMTP_PASSWORD'))
        click.echo('SMTP configured' if ready else 'SMTP not configured: run configure-email')
        if os.environ.get('ARI_PUBLIC_URL','http://127.0.0.1:5000').startswith(('http://127.0.0.1','http://localhost')):click.echo('Reset links currently target this computer only. Use a public HTTPS URL for other devices.')
