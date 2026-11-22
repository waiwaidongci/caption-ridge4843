from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import connection
from src.config.settings import ARTIFACTS
from src.constants.enums import Role
from src.controllers.auth import allow, current
from src.domain import partner
from src.models.exports import Publication
from src.models.identity import User
from src.models.source import Dataset
from src.schemas.requests import PublishRequest
from src.services.audit import record
from src.utils import views
from src.utils.exports import write_publication

router = APIRouter()


def require_dataset(db, dataset_id, lock=False):
    item = db.get(Dataset, dataset_id, with_for_update=lock)
    if not item:
        raise HTTPException(404, '找不到指定的数据批次')
    return item


def require_publication(db, publication_id):
    item = db.get(Publication, publication_id)
    if not item:
        raise HTTPException(404, '找不到该发布记录')
    return item


def published_cells(db, dataset_id, lock=False):
    query = select(Publication).where(Publication.dataset_id == dataset_id)
    if lock:
        query = query.with_for_update()
    return [cell for item in db.scalars(query) for cell in item.snapshot['cells']]


@router.get('/publications')
def index(dataset_id: int | None = None, db: Session = Depends(connection), actor: User = Depends(current)):
    query = select(Publication)
    if dataset_id:
        query = query.where(Publication.dataset_id == dataset_id)
    query = query.order_by(Publication.id.desc()).limit(100)
    return [views.publication(item) for item in db.scalars(query)]


@router.get('/publications/preview')
def preview(dataset_id: int, granularity: str, start: str = '', end: str = '',
            db: Session = Depends(connection), actor: User = Depends(current)):
    dataset = require_dataset(db, dataset_id)
    table = partner.build_table(dataset.rows, granularity, start or None, end or None)
    atoms = partner.dataset_atoms(dataset.rows)
    spans = partner.find_violations(atoms, published_cells(db, dataset.id) + table['cells'])
    return {'table': views.display_table(table), 'publishable': not spans,
            'conflict': partner.describe_violations(atoms, spans) if spans else None}


@router.post('/publications', status_code=201)
def publish(body: PublishRequest, db: Session = Depends(connection),
            actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    # 锁定批次行使同批次的发布串行，随后的锁定读取能看到并发刚提交的表。
    dataset = require_dataset(db, body.dataset_id, lock=True)
    if body.granularity not in partner.GRANULARITIES:
        raise ValueError('出表粒度仅支持按日、按周或整段')
    start, end = partner.normalize_range(body.start, body.end)
    signature = partner.fingerprint(dataset.id, body.granularity, start, end)
    existing = db.scalar(select(Publication).where(Publication.fingerprint == signature))
    if existing:
        return {**views.publication(existing, detail=True), 'created': False}
    table = partner.build_table(dataset.rows, body.granularity, start, end)
    atoms = partner.dataset_atoms(dataset.rows)
    cells = published_cells(db, dataset.id, lock=True) + table['cells']
    spans = partner.find_violations(atoms, cells)
    if spans:
        conflict = partner.describe_violations(atoms, spans)
        record(db, actor.username, 'publication.blocked', dataset.id,
               granularity=body.granularity, start=start, end=end, conflicts=conflict)
        db.commit()  # 只落审计，不留发布记录：发布失败不算已发
        raise HTTPException(409, f'发布后，结合已发表的表可反推 {conflict} 的实耗，请调整日期范围或改用更粗的粒度')
    item = Publication(dataset_id=dataset.id, fingerprint=signature, granularity=body.granularity,
                       start=start, end=end, order_count=table['order_count'], hidden_count=table['hidden'],
                       snapshot=table, author=actor.username)
    db.add(item)
    db.flush()
    item.export_file = write_publication(item.id, dataset.name, table)
    record(db, actor.username, 'publication.published', item.id, dataset_id=dataset.id,
           granularity=item.granularity, start=start, end=end,
           order_count=item.order_count, hidden_count=item.hidden_count)
    db.commit()
    return {**views.publication(item, detail=True), 'created': True}


@router.get('/publications/{publication_id}')
def detail(publication_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    return views.publication(require_publication(db, publication_id), detail=True)


@router.get('/publications/{publication_id}/download')
def download(publication_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    item = require_publication(db, publication_id)
    if not item.export_file:
        raise HTTPException(409, '此记录尚无可下载文件')
    path = ARTIFACTS / item.export_file
    if not path.is_file():
        raise HTTPException(410, '导出文件已不可用，请重新发布')
    return FileResponse(path, media_type='text/csv', filename=f'partner-hours-{item.id}.csv')
