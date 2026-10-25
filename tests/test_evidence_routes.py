import base64
from io import BytesIO
from PIL import Image
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.main import app
from backend.config import POLICY
from backend.db import Session,Payment,Case,Evidence,Proposal
from backend.ai import Recommendation,Citation,VisualAssessment
from .conftest import reviewed_case,approved_refund


def photo(color='red'):
    output=BytesIO();Image.new('RGB',(80,60),color).save(output,format='PNG')
    return {'image_base64':base64.b64encode(output.getvalue()).decode(),'media_type':'image/png'}


def new_case(client,payment,**extra):
    r=client.post('/api/cases',json={'payment_id':payment['id'],'statement':'The organizer arrived damaged. Please refund five dollars.','requested_cents':500,**extra})
    assert r.status_code==201,r.text
    return r.json()


def test_image_is_authenticated_normalized_and_omitted_from_dashboard(client,payment):
    case=new_case(client,payment);path=f"/api/cases/{case['id']}/evidence"
    assert client.post(path,json=photo()).status_code==201
    image=client.get(path)
    assert image.status_code==200 and image.headers['content-type']=='image/png'
    assert image.headers['cache-control']=='no-store'
    with TestClient(app) as anon:
        assert anon.get(path).status_code==401
    current=client.get('/api/dashboard').json()['cases'][0]
    assert current['evidence']['sha256']
    assert 'image_base64' not in str(current) and 'image_bytes' not in str(current)
    assert 'image_base64' not in client.get(f"/api/cases/{case['id']}/packet").text


def test_image_change_supersedes_ready_proposal_and_versions_payment(client,payment):
    case=reviewed_case(client,payment);old=case['proposal']
    assert client.post(f"/api/cases/{case['id']}/evidence",json=photo()).status_code==201
    with Session() as session:
        assert session.get(Proposal,old['id']).state=='superseded'
        assert session.get(Payment,payment['id']).version==payment['version']+1
    assert client.post(f"/api/proposals/{old['id']}/approve",json={'confirmed':True,'fingerprint':old['fingerprint']}).status_code==409


def test_image_cannot_change_after_approval(client,payment):
    _,case=approved_refund(client,payment)
    assert client.post(f"/api/cases/{case['id']}/evidence",json=photo()).status_code==409
    with Session() as session:
        assert session.scalar(select(Evidence)) is None


def test_photo_preview_does_not_silently_claim_visual_review(client,payment):
    case=new_case(client,payment)
    client.post(f"/api/cases/{case['id']}/evidence",json=photo())
    response=client.post(f"/api/cases/{case['id']}/analyze")
    assert response.status_code==200,response.text
    proposal=response.json()['proposal']
    assert proposal['state']=='blocked' and proposal['visual_assessment'] is None
    assert proposal['evidence_sha256']
    assert client.post(f"/api/proposals/{proposal['id']}/approve",json={'confirmed':True,'fingerprint':proposal['fingerprint']}).status_code==409


def recommendation():
    return Recommendation(decision='refund',amount_cents=500,explanation='Visible cracking is consistent with the customer claim; merchant review is required.',citations=[Citation(source='policy',reference='P2',quote=POLICY['clauses']['P2'])],missing_information=[],visual_assessment=VisualAssessment(damage='damage_visible',consistency='matches_claim',observation='A crack is visible on the pictured organizer.'))


def test_photo_hash_is_bound_to_approvable_proposal(client,payment,monkeypatch):
    case=new_case(client,payment);path=f"/api/cases/{case['id']}/evidence"
    image=client.post(path,json=photo()).json()
    async def mock(*_):return recommendation(),'test-multimodal-model'
    monkeypatch.setattr('backend.main.analyze',mock)
    response=client.post(f"/api/cases/{case['id']}/analyze")
    assert response.status_code==200,response.text
    p=response.json()['proposal'];assert p['evidence_sha256']==image['sha256'] and p['state']=='ready'
    # Simulate a broken storage update bypassing the normal versioned route.
    with Session.begin() as session:
        session.scalar(select(Evidence).where(Evidence.case_id==case['id'])).sha256='a'*64
    assert client.post(f"/api/proposals/{p['id']}/approve",json={'confirmed':True,'fingerprint':p['fingerprint']}).status_code==409


def test_photo_change_during_ai_call_is_rejected(client,payment,monkeypatch):
    case=new_case(client,payment);client.post(f"/api/cases/{case['id']}/evidence",json=photo())
    async def mock(*_):
        with Session.begin() as session:
            session.scalar(select(Evidence).where(Evidence.case_id==case['id'])).sha256='b'*64
        return recommendation(),'test-model'
    monkeypatch.setattr('backend.main.analyze',mock)
    assert client.post(f"/api/cases/{case['id']}/analyze").status_code==409


def test_return_cost_difference_is_explicit_estimate(client,payment):
    case=new_case(client,payment,return_shipping_cents=600,restocking_cents=200)
    value=case['return_economics'];assert value['estimated_handling_cents']==800 and value['difference_cents']==300
    assert 'Not net margin' in value['disclaimer']
    assert new_case(client,payment,return_shipping_cents=600)['return_economics'] is None


@pytest.mark.parametrize('cost',[-1,1.5,True,'100',1000001])
def test_handling_estimates_require_bounded_integer_cents(client,payment,cost):
    assert client.post('/api/cases',json={'payment_id':payment['id'],'statement':'Please refund my damaged organizer.','requested_cents':500,'return_shipping_cents':cost}).status_code==422


def test_deny_zero_is_not_presented_as_invalid_refund_amount(client,payment,monkeypatch):
    case=new_case(client,payment)
    async def mock(*_):
        return Recommendation(decision='deny',amount_cents=0,explanation='This request is denied and no refund is proposed.',citations=[Citation(source='policy',reference='P3',quote=POLICY['clauses']['P3'])],missing_information=[]),'test-model'
    monkeypatch.setattr('backend.main.analyze',mock)
    p=client.post(f"/api/cases/{case['id']}/analyze").json()['proposal']
    assert p['state']=='blocked' and not any('greater than zero' in b for b in p['blockers'])


def test_non_ascii_approval_fingerprint_is_rejected_without_server_error(client,payment):
    case=reviewed_case(client,payment)
    response=client.post(f"/api/proposals/{case['proposal']['id']}/approve",json={'confirmed':True,'fingerprint':'\u2603'})
    assert response.status_code==400


def test_upload_stream_limit_cannot_be_bypassed_by_content_length(client,payment):
    case=new_case(client,payment)
    response=client.post(f"/api/cases/{case['id']}/evidence",content=b'x'*(3*1024*1024),headers={'Content-Type':'application/json','Content-Length':'1'})
    assert response.status_code==413


def test_evidence_daily_limit_rolls_back_payment_change(client,payment):
    from backend.db import Quota
    from datetime import datetime,timezone
    case=new_case(client,payment)
    with Session.begin() as session:
        session.add(Quota(key='images:'+datetime.now(timezone.utc).date().isoformat(),used=20))
        before=session.get(Payment,payment['id']).version
    assert client.post(f"/api/cases/{case['id']}/evidence",json=photo()).status_code==429
    with Session() as session:
        assert session.get(Payment,payment['id']).version==before
        assert session.scalar(select(Evidence)) is None
