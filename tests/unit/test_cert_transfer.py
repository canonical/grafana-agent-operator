
import json
import uuid
from unittest.mock import patch

import yaml
from ops.testing import Context, Model, Relation, State

from charm import GrafanaAgentMachineCharm as GrafanaAgentCharm

ctx = Context(GrafanaAgentCharm)

def test_ca_cert_saved_to_disk():
    written_path, written_text = "", ""
    def mock_write(_, path, text):
        nonlocal written_path, written_text
        written_path = path
        written_text = text

    model_uuid = uuid.uuid4()
    ca_cert_path = "/usr/local/share/ca-certificates"
    fake_cert = "-----BEGIN CERTIFICATE-----123-----END CERTIFICATE-----"
    remote_app_data = {
        "certificates": json.dumps([
            fake_cert
        ]),
        "version": "1"
    }

    # GIVEN a receive-ca-cert relation over certificates_transfer
    rel_id = 1
    certificate_transfer_relation = Relation(
        "receive-ca-cert",
        remote_app_data=remote_app_data,
        id=rel_id,
    )
    state = State(
        leader=True,
        relations=[
            certificate_transfer_relation
        ],
        model=Model(uuid=str(model_uuid))
    )

    # WHEN a relation is joined
    with patch(
        "charm.GrafanaAgentMachineCharm.write_file", new=mock_write
    ), patch("charm.GrafanaAgentMachineCharm.restart") as mock_restart:
        ctx.run(ctx.on.relation_changed(certificate_transfer_relation), state)

    # THEN the file must be written to disk with the correct name
    cert_path = f"{ca_cert_path}/receive-ca-cert-{model_uuid}-{rel_id}-0-ca.crt"
    assert written_path == cert_path

    # AND the content of the file must be equal to the CA cert in relation data
    written_cert = yaml.safe_load(written_text)
    assert written_cert == fake_cert

    # AND the snap must restart
    mock_restart.assert_called()

def test_ca_cert_deleted_from_disk():
    delete_path = ""
    def mock_delete(_, path):
        nonlocal delete_path
        delete_path = path

    model_uuid = uuid.uuid4()
    ca_cert_path = "/usr/local/share/ca-certificates"
    fake_cert = "-----BEGIN CERTIFICATE-----123-----END CERTIFICATE-----"
    remote_app_data = {
        "certificates": json.dumps([
            fake_cert
        ]),
        "version": "1"
    }

    # GIVEN a receive-ca-cert relation over certificates_transfer
    rel_id = 1
    certificate_transfer_relation = Relation(
        "receive-ca-cert",
        remote_app_data=remote_app_data,
        id=rel_id,
    )
    state = State(
        leader=True,
        relations=[
            certificate_transfer_relation
        ],
        model=Model(uuid=str(model_uuid))
    )

    # WHEN a relation is broken
    cert_path = f"{ca_cert_path}/receive-ca-cert-{model_uuid}-{rel_id}-0-ca.crt"
    with patch(
        "charm.GrafanaAgentMachineCharm.delete_file", new=mock_delete
    ), patch(
        "os.listdir", return_value=[cert_path]
    ):
        ctx.run(ctx.on.relation_broken(certificate_transfer_relation), state)

    # THEN the file must be deleted from disk
    assert delete_path == cert_path
