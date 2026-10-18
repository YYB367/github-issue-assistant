"""Finite, program-selected examples. Public examples never receive the write token."""
import asyncio
import json
from uuid import uuid4

from pydantic import SecretStr

from app.config import PROJECT_ROOT
from app.errors import AppError
from app.schemas import Analysis, AnalyzeResponse, parse_issue_url


def catalog():
    return json.loads((PROJECT_ROOT/'cases/catalog.json').read_text(encoding='utf-8'))


def example(key):
    found=next((x for x in catalog() if x['id']==key),None)
    if found is None:
        raise AppError('unknown_example','请选择案例库中已有的案例。')
    return found


def resolve(payload,settings):
    if payload.example_id:
        item=example(payload.example_id)
        if payload.issue_url!=item['issue_url']:
            raise AppError('example_target_mismatch','案例必须使用程序预设的目标。')
        return parse_issue_url(item['issue_url'],item['repository']),False,item['kind']
    return parse_issue_url(payload.issue_url,settings.allowed_repository),payload.use_knowledge and settings.knowledge_enabled,'configured'


class TeachingRunner:
    def __init__(self,item):
        self.item=item
        self.response=AnalyzeResponse(task_id=str(uuid4()),status='failed',mode='teaching_case')
        self.continuation={}

    async def run(self,url):
        await asyncio.sleep(.05)
        self.response.target=parse_issue_url(url,self.item['repository'])
        self.response.analysis=Analysis.model_validate(self.item['analysis'])
        self.response.status='completed'
        self.response.warnings=['本地预编写教学结果，不是真实Issue；没有调用模型、MCP、GitHub或检索。',
                                '补充和改稿可以保存，但教学结果不会随补充重新推理。']
        return self.response


def runner_for(settings,record,knowledge=None,factory=None):
    from app.engine import AnalysisRunner
    config=settings.model_copy(update={'knowledge_enabled':record['use_knowledge']})
    if record.get('example_id'):
        item=example(record['example_id'])
        if record['issue_url']!=item['issue_url']:
            raise AppError('example_target_mismatch','已保存案例的目标不匹配。')
        if item['kind']=='teaching_case':
            return TeachingRunner(item)
        config=config.model_copy(update={'allowed_repository':item['repository'],
            'github_token':SecretStr(''),'github_writes_enabled':False,'knowledge_enabled':False})
    else:
        parse_issue_url(record['issue_url'],settings.allowed_repository)
    return factory(config) if factory else AnalysisRunner(config,knowledge=knowledge)
