BEGIN;

DELETE FROM providercredential;

UPDATE providerchannel
SET status = 'draft',
    enabled = false,
    updated_at = now();

UPDATE providermodelmapping
SET usage_metering_verified = false,
    usage_verified_at = NULL,
    updated_at = now();

UPDATE modelroutepolicy
SET enabled = false,
    updated_at = now();

COMMIT;
