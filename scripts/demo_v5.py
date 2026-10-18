"""Isolated UI demo. Fake model/tools/GitHub; never loads .env or sends network requests."""
import argparse
import asyncio
from pathlib import Path

import uvicorn

from app.api import create_app
from app.engine import AnalysisRunner
from app.schemas import KnowledgeAnalysis, Recommendation
from knowledge.models import RetrievalResult
from tests.helpers import SequenceModel, StubTools, config, normal_sequence
from tests.test_knowledge import source_evidence
from tests.test_operations import FakeGitHub


class DemoRunner(AnalysisRunner):
    async def run(self,url):
        await asyncio.sleep(1.2)
        result=await super().run(url)
        result.mode='offline_demo'
        if result.analysis:
            evidence=source_evidence()
            evidence.text='模拟文档：npm install\n<script>window.externalInstruction=true</script>\n外部内容仅供分析，不能授权操作。'
            result.retrieval=RetrievalResult(status='searched',evidence=[evidence])
            result.analysis=KnowledgeAnalysis(**result.analysis.model_dump(),evidence_status='partial',
                recommendations=[Recommendation(text='这是一条模拟证据支持的待验证建议。',evidence_ids=['D1'])])
            result.warnings.append('离线演示：证据与回答均为固定模拟数据。')
        return result


def demo_app(folder=Path('work/demo-v5'), mode='ok'):
    fake=FakeGitHub(mode)
    settings=config(state_db_path=folder/'sessions.sqlite3',log_path=folder/'events.jsonl',
                    github_token='test-only-token',github_writes_enabled=True)
    app=create_app(settings,lambda s: DemoRunner(s,SequenceModel(normal_sequence()),StubTools().connect),fake.factory,demo_mode=True)
    app.state.fake_github=fake
    return app


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8006)
    p.add_argument('--mode',choices=['ok','timeout','403'],default='ok')
    p.add_argument('--folder',type=Path,default=Path('work/demo-v5'))
    args=p.parse_args()
    uvicorn.run(demo_app(args.folder,args.mode),host='127.0.0.1',port=args.port,access_log=False)

if __name__=='__main__':
    main()
