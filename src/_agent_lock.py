"""
Claude Agent SDK 환경변수 보호를 위한 공유 asyncio.Lock.
CLAUDECODE 환경변수는 프로세스 전체에서 공유되므로
모든 Claude Agent SDK 호출자가 동일한 Lock을 사용해야 한다.
"""
import asyncio

# 프로세스 전체에서 공유되는 단일 Lock
# generator.py 및 elaboration.py 등 모든 Claude Agent SDK 호출 모듈에서 import하여 사용한다.
AGENT_ENV_LOCK = asyncio.Lock()
