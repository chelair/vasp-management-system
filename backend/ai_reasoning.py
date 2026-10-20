"""Connection-level Chat Completions reasoning capabilities (docs: 2026-10-20).

Single source of truth for UI choices, save validation and request parameters.
Unknown gateways remain untouched unless the user explicitly selects a protocol.
"""
import re
from urllib.parse import urlsplit

EFFORTS=('default','none','minimal','low','medium','high','xhigh','max')
LABELS={'default':'跟随模型默认','none':'关闭思考','minimal':'最少思考','low':'低','medium':'中','high':'高','xhigh':'更高','max':'最高'}
OPENAI={
    'gpt-5':('minimal','low','medium','high'),
    'gpt-5-mini':('minimal','low','medium','high'),
    'gpt-5-nano':('minimal','low','medium','high'),
    'gpt-5.1':('none','low','medium','high'),
    'gpt-5.2':('none','low','medium','high','xhigh'),
    'gpt-5.4':('none','low','medium','high','xhigh'),
    'gpt-5.5':('none','low','medium','high','xhigh'),
    **{m:('none','low','medium','high','xhigh','max') for m in ('gpt-5.6','gpt-5.6-sol','gpt-5.6-terra','gpt-5.6-luna')},
    'gpt-6-sol':('none','low','medium','high','xhigh','max'),
    'gpt-6-luna':('none','low','medium','high','xhigh','max'),
    'gpt-6.1-sol':('low','medium','high','xhigh','max'),
    'gpt-6-astra':('low','medium','high','xhigh','max'),
    'o1':('low','medium','high'),'o3':('low','medium','high'),
    'o3-mini':('low','medium','high'),'o4-mini':('low','medium','high'),
}
DEEPSEEK=('deepseek-flash','deepseek-v4-pro','deepseek-v4-flash')


def capabilities(connection):
    host=urlsplit(connection.get('base_url','')).hostname
    requested=connection.get('reasoning_api','auto')
    provider=requested if requested!='auto' else {'api.openai.com':'openai','api.deepseek.com':'deepseek'}.get(host,'unknown')
    model=connection.get('model','').lower()
    known=next((key for key in OPENAI if model==key or re.fullmatch(re.escape(key)+r'-\d{4}-\d{2}-\d{2}',model)),None)
    levels=();policy='supported';note='未识别可调思考能力；默认不发送思考参数。代理接口可手动选择兼容类型。'
    verified=False
    if provider=='deepseek':
        if model in DEEPSEEK or (requested=='deepseek' and model not in ('deepseek-chat','deepseek-reasoner')):
            levels=('none','low','high','max');verified=model in DEEPSEEK
            note='思考与回答共用输出额度；更高档位可能需要更多时间与额度。'
        else:note='旧版DeepSeek型号不提供本应用的深度档位；保留原默认行为。'
    elif provider=='openai':
        if known:
            levels=OPENAI[known];verified=True;note='按该型号显示支持的档位；思考与最终回答共用输出额度。'
            if known in ('gpt-6-astra','gpt-6.1-sol'):
                policy='unsupported';note+=' 此型号暂不支持本工作区的工具调用，可关闭会话工作区使用普通聊天，或更换支持工具的型号。'
            elif known in ('gpt-6-sol','gpt-6-luna'):
                policy='none_only';note+=' 此型号调用工作区工具需要关闭思考；不会自动降低所选档位。'
        elif requested=='openai':
            levels=EFFORTS[1:];note='自定义兼容接口：档位由服务商决定，选择前请确认支持；接口拒绝时不会自动降档或重试。'
    if levels and not verified:note+=' 当前接口能力未实测，由所选兼容协议传递。'
    return {'provider':provider,'verified':verified,'options':[{'value':v,'label':LABELS[v]} for v in ('default',*levels)],'tool_policy':policy,'note':note}


def validate(connection):
    if connection.get('reasoning_api','auto') not in ('auto','openai','deepseek'):raise ValueError('思考接口类型无效')
    effort=connection.get('reasoning_effort','default')
    if effort not in {o['value'] for o in capabilities(connection)['options']}:raise ValueError('所选思考深度不适用于此模型/接口，请重新选择')


def effective(connection):
    effort=connection.get('reasoning_effort','default')
    caps=capabilities(connection)
    if effort=='default' and caps['provider']=='deepseek' and connection.get('model') in DEEPSEEK:
        # Old connection switches remain effective without rewriting ciphertext.
        return 'none' if connection.get('thinking_mode')=='disabled' else 'default'
    return effort


def validate_tools(connection,enabled):
    if not enabled:return
    policy=capabilities(connection)['tool_policy']
    if policy=='unsupported' or policy=='none_only' and effective(connection)!='none':
        raise ValueError('此模型的当前思考设置不支持当前工作区工具；请关闭会话工作区，或选择支持工具的模型/档位')


def parameters(connection):
    validate(connection)
    caps=capabilities(connection);effort=connection.get('reasoning_effort','default');out={}
    if effort!='default':
        out['reasoning_effort']=effort
        if caps['provider']=='deepseek':out['thinking']={'type':'disabled' if effort=='none' else 'enabled'}
    elif caps['provider']=='deepseek' and connection.get('model') in DEEPSEEK:
        mode=connection.get('thinking_mode','default')
        if mode in ('enabled','disabled'):out['thinking']={'type':mode}
    return out
