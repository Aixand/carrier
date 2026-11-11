from aixand_filesystem import verify_private

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json

import pytest

from carrier import ensure_session
from carrier.service import Store


def test_concurrent_provisioning_preserves_one_identity(tmp_path):
    database, credentials = tmp_path / 'carrier.db', tmp_path / 'user.json'
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: ensure_session(database=database, credentials=credentials, address='suite/test/user'), range(8)))
    assert all(path == credentials for path in paths)
    verify_private(credentials)
    value = json.loads(credentials.read_text())
    with Store(database).db() as db:
        rows = db.execute('SELECT address, token_hash FROM sessions').fetchall()
    assert len(rows) == 1
    assert rows[0]['token_hash'] == hashlib.sha256(value['token'].encode()).hexdigest()
    with pytest.raises(ValueError, match='match'):
        ensure_session(database=database, credentials=credentials, address='different')
    assert json.loads(credentials.read_text()) == value


@pytest.mark.parametrize('committed', [False, True])
def test_interrupted_provisioning_restores_original_token(tmp_path, committed):
    database, credentials = tmp_path / 'carrier.db', tmp_path / 'stage.json'
    value = {'address': 'workflow/test/stage', 'token': 'persisted-private-token'}
    credentials.with_suffix('.json.pending').write_text(json.dumps(value))
    if committed:
        with Store(database).db() as db:
            db.execute('INSERT INTO sessions(address,token_hash) VALUES (?,?)', (value['address'], hashlib.sha256(value['token'].encode()).hexdigest()))
    ensure_session(database=database, credentials=credentials, address=value['address'])
    assert json.loads(credentials.read_text()) == value
    assert not credentials.with_suffix('.json.pending').exists()


def test_missing_credentials_cannot_replace_an_existing_identity(tmp_path):
    database, credentials = tmp_path / 'carrier.db', tmp_path / 'lost.json'
    store = Store(database)
    token = store.provision('existing')
    with pytest.raises(ValueError, match='different credentials'):
        ensure_session(database=database, credentials=credentials, address='existing')
    assert not credentials.exists()
    with store.db() as db:
        assert db.execute('SELECT token_hash FROM sessions WHERE address=?', ('existing',)).fetchone()[0] == hashlib.sha256(token.encode()).hexdigest()
