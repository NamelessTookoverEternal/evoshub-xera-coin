-- Run once, at the same moment you deploy the backend containing
-- AGREEMENT_VERSION = "xera-miner-agreement-2026-11-v2" (python/xera/agreement.py).
-- Every miner is asked to accept v2 the next time they start a session.
UPDATE xera_launch_config
   SET agreement_version = 'xera-miner-agreement-2026-11-v2'
 WHERE id = 1;
