# Getting Started

## Quickstart

> Note: MemberMatters only supports running in Docker on Linux. Installing Docker is outside the scope of this guide,
> please consult your favourite search engine for tips.

To get started, download the latest version from docker hub using the following command:

```bash
docker pull membermatters/membermatters
```

Create a file to contain all of your environment variables.
Place it somewhere you won't forget like `/usr/app/env.list`. This file is where Docker gets the environment
variables from. You'll need at least the following:

```
# /usr/app/env.list
MM_ENV=Production
MM_SECRET_KEY=<generate a long random string, keep it private>
MM_ALLOWED_HOSTS=portal.example.org,www.example.org
```

> **Required in production.** When `MM_ENV=Production`, the container refuses to boot
> if `MM_SECRET_KEY` or `MM_ALLOWED_HOSTS` is missing — the process exits with
> `ImproperlyConfigured` before serving any requests.
>
> - `MM_SECRET_KEY` is used to sign Django sessions and JWT access tokens. Generate a
>   long random value (e.g. `python -c "import secrets; print(secrets.token_urlsafe(64))"`),
>   never reuse the bundled dev key, and treat it like a database password — anyone who
>   has it can forge a session for any user, including admins.
> - `MM_ALLOWED_HOSTS` is a comma-separated list of the public hostnames your portal
>   answers on. Setting it narrows the surface for Host-header attacks (cache poisoning,
>   spoofed password-reset links).
>
> **Multi-container deployments (docker-compose, Kubernetes, CapRover, etc.):** these
> two variables must be set on **every** service that runs the MemberMatters image —
> the web app, the Celery worker, and the Celery beat scheduler — because each one
> imports Django settings at startup. The example `docker/docker-compose.yml` and
> `docker/caprover.yaml` only declare them on the web app service; if you copy from
> those templates, propagate the variables to the worker and beat services too (a YAML
> anchor or `env_file:` shared across services keeps it DRY). The `--env-file` quickstart
> above is single-container and is unaffected.

Once you've downloaded the docker image and configured your environment variables, you'll need to create a container
and mount a volume. Replace `/usr/app/` with the location you'd like to store your database and other data.

```bash
docker create -p 8000:8000 --name membermatters --restart always --env-file /usr/app/env.list -v /usr/app/:/usr/src/data membermatters/membermatters
```

After you've created the container (using the command above) you can start/stop/restart it with:

```bash
docker start membermatters
docker stop membermatters
docker restart membermatters
```

Once your container is running, you will probably want to load the initial database fixtures so there's an account you can use to login with. To do so, connect to your running docker container:

```bash
docker exec -it membermatters bash
```

and run the following:

```bash
python3 manage.py loaddata initial
```

Once you've loaded the initial fixtures, you will be able to login with the default admin account details:

```
Email: default@example.com
Password: MemberMatters!
```

The first thing you should do is change the email address and password of the default admin account.

Once you've done this, your MemberMatters instance is ready for configuration. You should now head to [post installation steps](/docs/POST_INSTALL_STEPS.md) for important instructions on setting up and customising your instance.

## Deployment Tips

- MemberMatters runs on port 8000 by default. You should run a reverse proxy in front of it
  so you can protect all traffic with HTTPS. Please consult your favourite search engine on how to setup a reverse proxy.
  We recommend that you use nginx with let's encrypt.
- MemberMatters is designed to run on site if you have any door, interlock or memberbucks devices. However, some parts
  need reliable networking and internet to function. Please keep this in mind and make sure you perform thorough
  testing before relying on it.

## Updating your instance

Docker containers are meant to be disposable, so you'll need to delete it and make a fresh one from the latest image.
We suggest writing a bash script like the one below:

```bash
# update.sh
echo "checking for new docker image"
docker pull membermatters/membermatters
echo "Stopping the docker container"
docker stop membermatters
echo "Removing the old docker container"
docker rm membermatters
echo "Creating new docker container"
docker create -p 8000:8000 --name membermatters --restart always --detach --env-file /usr/app/env.list -v /usr/app/:/usr/src/data membermatters/membermatters
echo "Running new docker container"
docker start membermatters
```

## Kiosk Mode

MemberMatters also offers a kiosk mode. You can build this by running `API_BASE_URL=https://portal.example.org npm run build:electron` after reading through the development instructions in the `frontend` folder. At this time, we do not offer precompiled binaries for download.

This command will compile an electron based application that you can run on a machine set up as a kiosk. We recommend that you run the build command on the machine you intend to use as a kiosk to reduce compatibility problems due to different OS versions and/or architectures. For
security reasons, kiosk builds will only have limited profile functionality and are primarily meant
to allow members to sign in/out of site and use basic features of MemberMatters. Be sure to specify the full URL to your MemberMatters instance, including the protocol (http or https).

The first time a kiosk connects, you will have to "authorise" it from the MemberMatters dashboard. You should see the kiosk show up with it's serial number. Open the kiosk to edit it, then click on authorise to allow full functionality. This is to prevent "random" kiosks being able to connect to your MemberMatters instance.

### Linux

You may need to install ffmpeg and a chromium run time.
