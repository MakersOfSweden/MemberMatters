# Upgrading

Notes for upgrading an existing MemberMatters instance. If you are installing for the first time, follow the [getting started](/docs/GETTING_STARTED.md) instructions instead — nothing here applies to a new install.

Upgrade in this order:

1. **Read the notes for your version.** Changes are grouped by the releases they apply to, newest first. Read every group that includes the version you are on, and do what they ask before you go on. Some checks run on the portal while it is still on the old version, so do them before you stop it.
2. **Back up your database.** Some upgrades move or convert data, and going back to the previous image does not undo that. [Going back](#going-back-to-the-previous-version) restores this backup.

   - **SQLite**, the getting started default: stop the container and copy the database file out of the folder you mounted, which is `/usr/app/` in the getting started instructions. The container writes that file as root, so run `cp` as root or with `sudo`.

     ```bash
     docker stop membermatters
     cp /usr/app/db.sqlite3 /usr/app/db.sqlite3.backup
     ```

   - **PostgreSQL under docker compose**, where `mm-postgres` is the database service:

     ```bash
     docker compose exec -T mm-postgres pg_dump -U membermatters membermatters > membermatters-backup.sql
     ```

   - **A database server you run yourself**: use its own backup tool, such as `pg_dump` or `mysqldump`.

3. **Keep the image you are running.** Pulling the new image moves the name `membermatters/membermatters` to it, so give the current one a name of its own. Going back then works without knowing which version you ran.

   - **Single container**:

     ```bash
     docker tag "$(docker inspect --format '{{.Image}}' membermatters)" membermatters/membermatters:before-upgrade
     ```

   - **docker compose**, from the directory holding your docker-compose.yml:

     ```bash
     docker tag "$(docker inspect --format '{{.Image}}' "$(docker compose ps -aq mm-webapp)")" membermatters/membermatters:before-upgrade
     ```

4. **Move to the new image.** Database migrations run automatically every time the web container starts, so upgrading means replacing the container with one made from the new image. `docker restart` is not enough: it starts the same container again, on the image it was created from.

   - **Single container**, as in the getting started instructions: follow [Updating your instance](/docs/GETTING_STARTED.md#updating-your-instance). Pull the new image, then stop, remove and re-create the container with the same `docker create` command you installed it with, and start it.
   - **docker compose**: from the directory holding your [docker-compose.yml](/docker/docker-compose.yml), run:

     ```bash
     docker compose pull
     docker compose up -d
     ```

   - **CapRover, Kubernetes or another setup** that runs the web app, the Celery worker and the Celery beat scheduler as separate services: move all three to the new image at the same time. Only the web app runs the migrations, and a worker or scheduler left on the old image expects the database as its own version left it. Moving the settings to a new table (django-constance 4, below) is one such change: an old worker can no longer read any setting.

## Going back to the previous version

If the new version doesn't work for you, go back to the image you kept in step 3 and restore the backup from step 2. Restore the backup as well: the new version changes the database as soon as it starts, and the previous version can't read the result. Anything changed since the backup is lost.

- **Single container** with SQLite, running `cp` as root or with `sudo` as in step 2:

  ```bash
  docker stop membermatters
  docker rm membermatters
  cp /usr/app/db.sqlite3.backup /usr/app/db.sqlite3
  ```

  Then create and start the container as you did in step 4, with `membermatters/membermatters:before-upgrade` in place of `membermatters/membermatters` at the end of the `docker create` command.

- **docker compose** with the bundled PostgreSQL: stop the services that use the database, then replace the database with the backup:

  ```bash
  docker compose stop mm-webapp mm-celery-worker mm-celery-beat
  docker compose exec -T mm-postgres dropdb --force -U membermatters membermatters
  docker compose exec -T mm-postgres createdb -U membermatters membermatters
  docker compose exec -T mm-postgres psql -q -U membermatters membermatters < membermatters-backup.sql
  ```

  Then set `image: membermatters/membermatters:before-upgrade` on the web app, the Celery worker and the Celery beat scheduler in your docker-compose.yml, and run `docker compose up -d`. Don't run `docker compose pull` first: the kept image exists only on your machine.

- **A database server you run yourself**: restore the backup with its own tool, then move your services back to the previous image.

## Upgrading from 3.8 or earlier

### Set MM_SECRET_KEY and MM_ALLOWED_HOSTS

With `MM_ENV=Production`, the portal now refuses to start unless both are set. Older versions fell back to a secret key that is published with the source code, and answered on any hostname. The getting started instructions for 3.8 didn't mention either variable, so check yours before you upgrade. A container missing either one keeps restarting, and its log ends with an error like this:

```
django.core.exceptions.ImproperlyConfigured: MM_SECRET_KEY must be set when MM_ENV=Production.
```

Once `MM_SECRET_KEY` is set, the same error names `MM_ALLOWED_HOSTS` if that is still missing.

- `MM_SECRET_KEY`: if you already set one, keep it. Otherwise generate a long random value, for example with `python3 -c "import secrets; print(secrets.token_urlsafe(64))"`, and keep it private. The new key signs everyone out once, in the browser and in the mobile app.
- `MM_ALLOWED_HOSTS`: every hostname the portal is reached by, separated by commas, such as `portal.example.org`. Leave out `https://` and any port. A request for a name that isn't listed gets `400 Bad Request`, so include any local name or IP address that kiosks or a monitoring service use.

For a single container, add both to your `env.list`. Under docker compose, CapRover or Kubernetes, set them on the web app, the Celery worker and the Celery beat scheduler: each one reads the settings, so each one stops without them. Give all three the same `MM_SECRET_KEY`, and replace a placeholder such as `CHANGE_ME` from the example [docker-compose.yml](/docker/docker-compose.yml).

While you are there, consider setting `MM_NUM_PROXIES` too. Rate limiting on sign-up, login and password reset, new in this release, needs it to tell visitors apart. See [Getting Started](/docs/GETTING_STARTED.md) for the value.

### Check the key the portal signs sign-ins with (django-oidc-provider 0.9)

If other services, such as Moodle or a wiki, let members sign in with their MemberMatters account, the portal signs those sign-ins with an RSA key stored under OpenID Connect Provider → RSA Keys in the Django admin. This release reads those keys with a stricter library. Two kinds of key used to work and now stop every such sign-in until they are removed: a key pasted in the OpenSSH format that `ssh-keygen` writes by default (it starts with `-----BEGIN OPENSSH PRIVATE KEY-----`), and a public key stored next to a working private one.

If no other service signs in through the portal, there is nothing to do. Otherwise, check your keys before or after you upgrade. Under docker compose, replace `docker exec membermatters` with `docker compose exec mm-webapp`:

```bash
docker exec membermatters python3 manage.py shell -v 0 -c "
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from oidc_provider.models import Client, RSAKey
def usable(key):
    try:
        load_pem_private_key(key.encode(), None)
        return True
    except Exception:
        return False
for key in RSAKey.objects.all():
    print('RSA key', key.id, 'is fine' if usable(key.key) else 'needs replacing')
for client in Client.objects.filter(jwt_alg='HS256', client_secret=''):
    print('Client', client.name, 'needs RS256')
"
```

For each key that needs replacing, create a new one with `docker exec membermatters python3 manage.py creatersakey`, then delete the old one in the Django admin. The services pick up the new key the next time someone signs in. A client listed as needing RS256 has no secret to sign with: set its JWT algorithm to RS256 under OpenID Connect Provider → Clients. RS256 needs an RSA key, so if the check listed none, create one with `creatersakey` first.

### Redis TLS options must be lowercase (Channels 4)

This release updates the library the portal uses to reach Redis, which carries messages between the portal and door, interlock and memberbucks devices. If your `MM_REDIS_HOST` is a `rediss://` address with an `ssl_cert_reqs` option, write its value in lowercase: `ssl_cert_reqs=required`, `optional` or `none`. The uppercase form (`CERT_REQUIRED`) still works for background tasks, but devices can no longer connect with it, and the door buttons in Admin Tools fail.

Plain `redis://` addresses, including the one in the bundled [docker-compose.yml](/docker/docker-compose.yml), need no change.

### Database and proxy requirements (Django 5.2)

This release moves the portal from Django 3.2 to 5.2, which is stricter about two parts of your setup.

#### Newer database versions

Django 5.2 will not work with a database server older than:

| Database | Minimum |
| --- | --- |
| PostgreSQL | 14 |
| MySQL | 8.0.11 |
| MariaDB | 10.5 |

If you use SQLite (the default in the [getting started](/docs/GETTING_STARTED.md) instructions, and built into the image) or the database from the bundled [docker-compose.yml](/docker/docker-compose.yml), there is nothing to do.

If MemberMatters connects to a database server you run yourself, check its version **before** you pull the new image. This asks the running portal, so it reports the database it is actually configured to use. Under docker compose, replace `docker exec membermatters` with `docker compose exec mm-webapp`:

```bash
docker exec membermatters python3 manage.py shell -v 0 -c "from django.db import connection; c = connection.cursor(); c.execute('select version()'); print(c.fetchone()[0])"
```

If the server is too old, upgrade it first. Otherwise the container still starts and the page still loads, but nobody can log in: every request that needs the database fails, and the container log shows an error such as `PostgreSQL 14 or later is required (found 13.4).` Going back to the previous image fixes it: the upgrade can't reach a database that old, so it hasn't changed any of your data.

#### Your reverse proxy must pass on the address the browser used

Django now checks that changes sent from a browser — a member saving their profile, an admin logging in to the Django admin — come from the same address the portal is served at. The portal learns that address from two headers your reverse proxy sends: `Host`, with the name and any port the browser used, and `X-Forwarded-Proto`, which says whether the browser used HTTPS. When a reverse proxy handles HTTPS for you, the portal only knows it is being reached over HTTPS if the proxy says so. If either header is wrong or missing, that check fails: members can still log in, but nothing they save goes through, and the Django admin login answers with "CSRF verification failed". Each failed admin login leaves a line like this in the container log:

```
Forbidden (Origin checking failed - https://portal.example.org does not match any trusted origins.): /admin/login/
```

If you set up nginx as described in [Post Installation Steps](/docs/POST_INSTALL_STEPS.md) and nothing sits in front of it, your proxy already sends both headers and there is nothing to do. Otherwise, check your proxy's configuration before you upgrade. For nginx, the location that forwards to MemberMatters needs both of these lines; other proxies have an equivalent setting:

```nginx
proxy_set_header Host $http_host;
proxy_set_header X-Forwarded-Proto $scheme;
```

`$http_host` passes on the address as the browser sent it, including a port such as the one in `https://portal.example.org:8443`. The `$host` in Post Installation Steps drops the port, which works only on the standard ports 80 and 443. A proxy that adds the standard port itself, as `proxy_set_header Host $host:$server_port;` does, works too: like browsers, the portal leaves out `:443` for HTTPS and `:80` for HTTP.

**Cloudflare in front of your proxy.** Cloudflare tells your proxy in `X-Forwarded-Proto` whether the visitor used HTTPS. In its Flexible SSL mode, though, it connects to your proxy over plain HTTP, so the `$scheme` line above replaces that `https` with `http` and the check fails. In the Cloudflare dashboard, under SSL/TLS → Overview, set the encryption mode to Full (strict): Cloudflare then connects to your proxy over HTTPS, which needs a certificate from a public authority, such as the one certbot set up in Post Installation Steps, or a Cloudflare Origin CA certificate. If Cloudflare has to reach your proxy over plain HTTP, for example through a Cloudflare Tunnel to an `http://` address, and every request comes through Cloudflare, pass on its header instead:

```nginx
proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
```

### Settings move to a new table and format (django-constance 4)

The settings you edit in the Django admin, under Constance → Config, are stored in a single table, which used to be named `constance_config`. django-constance moves those rows into a table named `constance_constance` and drops the old one. It then converts each saved value from Python's pickle format to JSON.

There is nothing for you to do. The migration copies every row across and converts it, so your settings — including API keys, Stripe configuration and email templates — keep their values.

The conversion can't be undone. To go back to an older version after upgrading, restore the backup you took first, as described in [Going back](#going-back-to-the-previous-version). Older versions don't understand the converted settings.

If you want to check, count the settings that have a value before you upgrade:

```bash
docker exec membermatters python3 manage.py shell -v 0 -c "from django.db import connection; c = connection.cursor(); c.execute('select count(*) from constance_config where value is not null'); print(c.fetchone()[0])"
```

and count them again in the new container:

```bash
docker exec membermatters python3 manage.py shell -v 0 -c "from django.db import connection; c = connection.cursor(); c.execute('select count(*) from constance_constance'); print(c.fetchone()[0])"
```

Under docker compose, replace `docker exec membermatters` with `docker compose exec mm-webapp`.

The second number should be at least the first. It can be higher, because the portal saves a setting's default the first time it reads one that was never saved. If it is lower, restore your backup rather than re-entering the settings by hand.

The first count leaves out settings stored without a value. The upgrade deletes those, and the portal saves their default the next time it reads them.

### Dashboard cards move to Admin Tools

Older versions configured the member dashboard through a setting named `HOME_PAGE_CARDS`. It is replaced by the Dashboard Cards editor under Admin Tools, and the upgrade creates a card for each entry in your old setting, so your dashboard looks the same afterwards.

If the setting isn't valid JSON, no cards are imported and the container log says so. Enter them under Admin Tools → Dashboard Cards instead.
