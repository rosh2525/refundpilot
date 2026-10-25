import pytest
from sqlalchemy import select,func
from backend.db import Session,Payment,Refund,Job,Audit
from backend.lab import run_scenario

@pytest.mark.parametrize('scenario',['duplicate_approval','competing_approvals','stale_policy','prompt_injection'])
def test_lab_checks_actual_approval_in_disposable_state(client,scenario):
    with Session() as session:
        before=[session.scalar(select(func.count()).select_from(model)) for model in (Payment,Refund,Job,Audit)]
    result=run_scenario(scenario)
    assert result['passed'],result
    assert result['environment']=='isolated_simulation'
    assert 'No merchant records' in result['disclaimer']
    with Session() as session:
        assert [session.scalar(select(func.count()).select_from(model)) for model in (Payment,Refund,Job,Audit)]==before
    if scenario=='duplicate_approval':
        assert len(result['requests'])==5
        assert len({r['operation_id'] for r in result['requests'] if r['status']==200})==1


def test_lab_routes_require_auth_and_csrf(client):
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as anon:
        assert anon.get('/api/lab').status_code==401
    assert client.post('/api/lab/run',json={'scenario':'stale_policy'},headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert client.post('/api/lab/run',json={'scenario':'not-a-scenario'}).status_code==422
    assert client.post('/api/lab/run',json={'scenario':'stale_policy'}).json()['passed']
