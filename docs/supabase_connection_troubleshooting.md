# Supabase Connection Troubleshooting

## Direct DB hostname fails with getaddrinfo / IPv6

The direct Supabase DB hostname (`db.<ref>.supabase.co`) may resolve only to an IPv6
address on some Windows setups. Python's psycopg raises:

```
psycopg.OperationalError: failed to resolve host 'db.<ref>.supabase.co': getaddrinfo failed
```

**Fix:** Use the Supabase **pooler** connection string instead of the direct DB URL.
In the Supabase dashboard go to **Project Settings → Database → Connection pooling**
and copy the Session mode URI. Set it in `.env`:

```
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

The pooler endpoint uses a hostname that resolves correctly over IPv4.

## Security reminder

Never commit `.env` to version control. Confirm `.env` is listed in `.gitignore` before
every commit that touches connection strings.

## Verify the fix

```powershell
cd C:\DevProjects-b\AtlasDB\src
python -m db.schema
```

Expected output:

```
Tables created successfully
Migrations applied successfully
Schema up to date.
```
