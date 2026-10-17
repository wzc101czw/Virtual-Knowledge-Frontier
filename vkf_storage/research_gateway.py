"""Audit model calls without persisting prompts or API credentials."""
from __future__ import annotations
import hashlib
from .core import Storage
from .importers import request_model_json


def call(st:Storage, *, system:str,query:str,model:str,api_base:str,timeout:int,
         task:str,max_tokens:int,purpose:str='extraction',conversation_id:str|None=None)->dict:
    fingerprint=hashlib.sha256((system+'\n'+query).encode('utf-8')).hexdigest()
    record=st.log_model_call(purpose=purpose,model_id=model,
         prompt_version=task+'-v1',input_fingerprint=fingerprint,
         conversation_id=conversation_id)
    try:
        output=request_model_json(system,query,model,api_base,timeout,max_tokens=max_tokens,task=task)
    except Exception as exc:
        st.finish_model_call(record['id'],success=False,error_message=str(exc)[:700])
        raise
    st.finish_model_call(record['id'],success=True)
    return output
