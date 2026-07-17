# Transparency operations

The `/transparency` page carries two artifacts. Both only work if they
are maintained; a stale canary is indistinguishable from a triggered one
— which is the point, so hold the discipline.

## Reproducible-build attestation

1. Build with the commit baked in:
   `docker build --build-arg BUILD_COMMIT=$(git rev-parse HEAD) -t pli .`
2. Push, note the registry digest, set `PLI_IMAGE_DIGEST=sha256:…` in the
   deployment env, redeploy.
3. Anyone can now: check out the commit, rebuild, compare — or pull the
   image by digest and inspect it against the repo.

## Warrant canary

Quarterly (put it in the calendar — 1 Jan / 1 Apr / 1 Jul / 1 Oct):

1. Review whether any legal demand concerning user data was received.
2. Update `PLI_TRANSPARENCY_REQUESTS` (count) and `PLI_CANARY_UPDATED`
   (today's date). Redeploy.
3. Optionally publish a PGP-signed copy of the statement in the repo so
   the history is independently verifiable.

If a demand arrives with a gag order: **do not update the canary**. Its
silence is the only statement you can lawfully make. Talk to counsel
before doing anything else.

Remember what any demand can actually yield: outside a live round,
nothing exists; during one, peppered hashes and sealed blobs with a
lifespan of days, plus organizer account records. Say exactly that,
every time, to every authority — it is true by construction and the test
suite proves it.
