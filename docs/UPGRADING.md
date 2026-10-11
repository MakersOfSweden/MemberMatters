# Upgrading

Notes for upgrading an existing MemberMatters instance. If you are installing for the first time, follow the [getting started](/docs/GETTING_STARTED.md) instructions instead — nothing here applies to a new install.

Upgrade in this order:

1. **Read the notes for your version.** Changes are grouped by the releases they apply to, newest first. Read every group that includes the version you are on, and do what they ask before you go on.
2. **Back up your database.** Upgrades change the database, and going back to the previous image does not undo that. [Going back](#going-back-to-the-previous-version) restores this backup.

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

   - **CapRover, Kubernetes or another setup** that runs the web app, the Celery worker and the Celery beat scheduler as separate services: move all three to the new image at the same time. Only the web app runs the migrations, and a worker or scheduler left on the old image expects the database as its own version left it.

## Going back to the previous version

If the new version doesn't work for you, go back to the image you kept in step 3 and restore the backup from step 2. Restore the backup as well: the new version changes the database as soon as it starts, and the previous version doesn't work reliably with the changed database. Anything changed since the backup is lost.

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

For a single container, add both to your `env.list`. Under docker compose, CapRover or Kubernetes, set them on the web app, the Celery worker and the Celery beat scheduler: each one reads the settings, so each one stops without them. Give all three the same `MM_SECRET_KEY`, and replace a placeholder such as the `CHANGE_ME` that older copies of the example docker-compose.yml carried. The current [docker-compose.yml](/docker/docker-compose.yml) shows one way: all three read both from a file named `membermatters.env` next to it, through `env_file:`.

Set `MM_NUM_PROXIES` too. Rate limiting on sign-up, login and password reset, new in this release, needs it to tell visitors apart. See [Getting Started](/docs/GETTING_STARTED.md) for the value.

### Check that no two members share a Stripe customer ID

This release lets each Stripe customer belong to only one member. If two members share one, for example because an admin copied it by hand, the upgrade stops: the container keeps restarting, and its log ends with an `IntegrityError` about `stripe_customer_id`. Check before you upgrade, on the version you run now. Under docker compose, replace `docker exec membermatters` with `docker compose exec mm-webapp`:

```bash
docker exec membermatters python3 manage.py shell -v 0 -c "
from django.db.models import Count
from profile.models import Profile
ids = Profile.objects.exclude(stripe_customer_id__isnull=True).exclude(stripe_customer_id='')
for row in ids.values('stripe_customer_id').annotate(n=Count('id')).filter(n__gt=1):
    print(row['stripe_customer_id'], 'is shared by', ', '.join(ids.filter(stripe_customer_id=row['stripe_customer_id']).values_list('user__email', flat=True)))
"
```

If it prints nothing, there is nothing to do. Otherwise open each listed member under Profile → Profiles in the Django admin, and clear the Stripe customer ID of the one who isn't that customer in your Stripe dashboard. If the upgrade already stopped there, go back as described in [Going back](#going-back-to-the-previous-version), clear the ID and upgrade again.
