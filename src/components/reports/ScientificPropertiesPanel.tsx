import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Checkbox, Collapse, Divider, Drawer, Input, InputNumber, Select, Space, Table, Tag, Typography } from 'antd';
import { discoverPropertyTasks, evaluateProperty, fetchPropertyRecipes } from '../../api/properties';
import type { PropertyRecipe, PropertyReport, PropertySelector, PropertyTarget, PropertyTask } from '../../api/properties';

const ROLES: Record<string, {key: string; label: string}[]> = {
  'oxygen_vacancy.neutral_single': [{key:'pristine',label:'完整模型'},{key:'defect',label:'单氧缺陷模型'}],
  relative_energy: [{key:'reference',label:'参考模型'},{key:'model',label:'比较模型'}],
  'adsorption.simple': [{key:'complex',label:'吸附复合体系'},{key:'surface',label:'洁净表面'},{key:'adsorbate',label:'一个吸附物参考'}],
  'neb.barrier': [{key:'path',label:'已有 NEB 路径'}],
  'work_function.difference': [{key:'reference',label:'参考表面'},{key:'model',label:'比较表面'}],
};
const STATUS: Record<string,string> = {AVAILABLE:'可用',MISSING:'缺失',INCOMPLETE:'未完成或未收敛',INVALID:'无效',STALE:'已过期',AMBIGUOUS:'待选择',UNKNOWN:'未验证',PARTIAL:'部分可计算',BLOCKED:'暂不可计算'};
const tag = (state: string) => <Tag color={state === 'AVAILABLE' ? 'green' : state === 'INVALID' ? 'red' : 'orange'}>{STATUS[state] || state}</Tag>;
const initialTargets = (pid: string): PropertyTarget[] => pid === 'oxygen_vacancy.neutral_single' ? [{label:'LMR'},{label:'LIC@LMR'}] : [{label:'体系1'}];

export default function ScientificPropertiesPanel({projectRef, projects, onClose}: {
  projectRef: string; projects: {id:string; name:string}[]; onClose: () => void;
}) {
  const { message } = App.useApp();
  const [recipes,setRecipes] = useState<PropertyRecipe[]>([]);
  const [pid,setPid] = useState('oxygen_vacancy.neutral_single');
  const [scopes,setScopes] = useState([projectRef]);
  const [tasks,setTasks] = useState<PropertyTask[]>([]);
  const [targets,setTargets] = useState<PropertyTarget[]>(initialTargets(pid));
  const [shared,setShared] = useState(false);
  const [hasMu,setHasMu] = useState(false);
  const [mu,setMu] = useState<number | null>(null);
  const [muSource,setMuSource] = useState('');
  const [conditions,setConditions] = useState('');
  const [side,setSide] = useState<string>();
  const [reaction,setReaction] = useState('');
  const [report,setReport] = useState<PropertyReport>();
  const [dirty,setDirty] = useState(false);
  const [busy,setBusy] = useState(false);
  const generation = useRef(0);
  const discovery = useRef(0);
  const searchTimer = useRef<ReturnType<typeof setTimeout>>();
  const recipe = recipes.find(r => r.property_id === pid);
  const changed = () => { generation.current++; setDirty(true); setBusy(false); };
  useEffect(() => {
    let active = true;
    fetchPropertyRecipes().then(r => { if (active) setRecipes(r.recipes); }).catch(e => message.error(e.message));
    return () => { active = false; generation.current++; discovery.current++; clearTimeout(searchTimer.current); };
  }, [message]);
  useEffect(() => {
    const version = ++discovery.current;
    setTasks([]);
    discoverPropertyTasks(scopes).then(r => {
      if (version !== discovery.current) return;
      setTasks(r.matches);
      if (r.truncated) message.info('候选超过100项，输入模型名可继续检索全部任务。');
    }).catch(e => { if (version === discovery.current) message.error(e.message); });
  }, [scopes,message]);
  const searchTasks = (query: string) => {
    clearTimeout(searchTimer.current);
    const version = ++discovery.current;
    searchTimer.current = setTimeout(() => {
      discoverPropertyTasks(scopes,query).then(r => {
        if(version !== discovery.current) return;
        setTasks(old => [...new Map([...old,...r.matches].map(t => [JSON.stringify([t.project_id,t.task_id]),t])).values()]);
      }).catch(e => {if(version === discovery.current) message.error(e.message);});
    },200);
  };
  const updateTarget = (index: number, field: string, value: string | number | PropertySelector) => {
    changed(); setTargets(old => old.map((t,i) => i === index ? {...t,[field]:value} : t));
  };
  const calculate = async () => {
    const version = ++generation.current;
    setBusy(true);
    try {
      const value = await evaluateProperty({property_id:pid,project_ids:scopes,targets,
        ...(pid === 'oxygen_vacancy.neutral_single' ? {common_oxygen_reference:shared,
          ...(hasMu ? {mu_O:{value_ev:mu,source:muSource,conditions}} : {})} : {}),
        ...(pid === 'work_function.difference' && side ? {surface_side:side} : {}),
        ...(pid === 'neb.barrier' && reaction ? {reaction_correspondence:reaction} : {}),
        ...(pid === 'adsorption.simple' && conditions ? {reference_conditions:conditions} : {})});
      if (version === generation.current) {setReport(value);setDirty(false);}
    } catch (e) {if (version === generation.current) message.error((e as Error).message);}
    finally {if (version === generation.current) setBusy(false);}
  };
  const download = () => {
    if (!report || dirty) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = report.report_id+'.json'; a.click(); URL.revokeObjectURL(url);
  };
  return <Drawer title="科学性质与数据需求" open onClose={onClose} width={1100} destroyOnClose>
    <Space direction="vertical" size="middle" style={{width:'100%'}}>
      <Select aria-label="科学性质" style={{width:'100%'}} value={pid} options={recipes.map(r => ({value:r.property_id,label:r.definition}))}
        onChange={value => {changed();setPid(value);setTargets(initialTargets(value));setReport(undefined);}}/>
      {recipe && <Alert type="info" message={recipe.formula} description={<>{recipe.scope}<br/>需要：{recipe.required_inputs.join('；')}</>}/>}
      <Typography.Text>检索项目（跨项目逐项核对权限）</Typography.Text>
      <Select aria-label="检索项目" mode="multiple" style={{width:'100%'}} value={scopes} options={projects.map(p => ({value:p.id,label:p.name}))}
        onChange={value => {if (!value.length || value.length>8) return;changed();setScopes(value);setTargets(initialTargets(pid));setReport(undefined);}}/>
      <Typography.Text type="secondary">按名称搜索并选择具体任务。名称只用于查找；结构关系、位点及收敛情况由证据核对。</Typography.Text>
      {targets.map((target,index) => <div key={index} style={{border:'1px solid #ddd',padding:16,borderRadius:8}}>
        <Space style={{marginBottom:12}}>
          <Input aria-label={`体系${index+1}名称`} value={target.label} onChange={e => updateTarget(index,'label',e.target.value)}/>
          {targets.length>1 && <Button onClick={() => {changed();setTargets(old => old.filter((_,i) => i !== index));}}>移除体系</Button>}
        </Space>
        {ROLES[pid].map(role => {
          const selector = (target[role.key] || {}) as PropertySelector;
          const item = report?.inputs.find(i => i.role === `${index}.${role.key}` && i.task?.task_id === selector.task_id);
          return <div key={role.key} style={{marginBottom:12}}>
            <Typography.Text>{role.label} </Typography.Text>
            <Select aria-label={`${target.label}-${role.key}`} showSearch onSearch={searchTasks} optionFilterProp="label" allowClear style={{width:'100%'}}
              placeholder="搜索模型名并选择具体任务" value={selector.task_id ? JSON.stringify([selector.project_id,selector.task_id]) : undefined}
              options={tasks.filter(t => pid !== 'neb.barrier' || t.task_type === 'neb').map(t => ({value:JSON.stringify([t.project_id,t.task_id]),label:`${projects.find(p=>p.id===t.project_id)?.name} / ${t.model_name} · ${t.task_type} · ${t.task_id}`}))}
              onChange={value => {const [project_id,task_id] = value ? JSON.parse(value) : [undefined,undefined]; updateTarget(index,role.key,task_id ? {project_id,task_id} : {});}}/>
            {item?.observations && item.observations.length>0 && <Select aria-label={`${target.label}-${role.key}-快照`} allowClear style={{width:'100%',marginTop:6}}
              placeholder="选择计算目录与观测版本" value={selector.observation_id}
              options={item.observations.map(o => ({value:o.observation_id,label:`${o.directory?.path || '未知目录'} · ${o.observation_id}`}))}
              onChange={value => {const updated = {...selector};if(value)updated.observation_id=value;else delete updated.observation_id;updateTarget(index,role.key,updated);}}/>}
          </div>;
        })}
      </div>)}
      <Button disabled={targets.length>=8} onClick={() => {changed();setTargets(old => [...old,{label:`体系${old.length+1}`}]);}}>添加体系或位点</Button>
      {pid === 'oxygen_vacancy.neutral_single' && <>
        <Checkbox checked={shared} onChange={e => {changed();setShared(e.target.checked);}}>确认各体系采用相同氧化学势和适用条件（缺参考数值时，只允许计算消去共同参考的差值）</Checkbox>
        <Checkbox checked={hasMu} onChange={e => {changed();setHasMu(e.target.checked);}}>明确设置氧化学势 μ_O，用于绝对形成能</Checkbox>
        {hasMu && <Space direction="vertical" style={{width:'100%'}}>
          <InputNumber aria-label="氧化学势" addonAfter="eV / O" value={mu} onChange={v => {changed();setMu(v);}}/>
          <Input aria-label="氧参考来源" placeholder="明确来源，例如 1/2 E(O₂) 与采用的修正；不是O₂总能量" value={muSource} onChange={e => {changed();setMuSource(e.target.value);}}/>
          <Input aria-label="氧参考条件" placeholder="适用温度、氧压、参考态和理论条件" value={conditions} onChange={e => {changed();setConditions(e.target.value);}}/>
        </Space>}
      </>}
      {pid === 'work_function.difference' && <Select aria-label="真空表面侧" placeholder="选择相同真空表面侧" value={side} options={[{value:'start',label:'坐标起始侧'},{value:'end',label:'坐标末端侧'}]} onChange={v => {changed();setSide(v);}}/>}
      {pid === 'neb.barrier' && <Input aria-label="反应路径对应" placeholder="比较能垒时，明确各路径的反应、方向和初末态对应" value={reaction} onChange={e => {changed();setReaction(e.target.value);}}/>}
      {pid === 'adsorption.simple' && <Input aria-label="吸附参考条件" placeholder="吸附物参考态及适用条件" value={conditions} onChange={e => {changed();setConditions(e.target.value);}}/>}
      <Space><Button aria-label="验证数据并计算" type="primary" loading={busy} onClick={calculate} disabled={hasMu && pid==='oxygen_vacancy.neutral_single' && (mu===null || !muSource.trim() || !conditions.trim())}>验证数据并计算</Button>
        <Button disabled={!report || dirty} onClick={download}>下载数据需求与结果</Button></Space>
      {report && <>
        <Divider/>
        <Space>{tag(report.status)}<Typography.Text>快照保存时间：{report.generated_at}</Typography.Text></Space>
        {dirty && <Alert type="warning" message="输入已修改，请重新验证；下方保留上次快照结果。"/>}
        <Table size="small" rowKey="key" pagination={false} dataSource={report.results} columns={[
          {title:'性质 / 比较方向',dataIndex:'label'},{title:'结果',render:(_,r) => `${r.value} ${r.units}`},{title:'公式',dataIndex:'formula'},
        ]}/>
        {report.targets.filter(t=>t.site).map((t,i)=><Typography.Text key={i}>{t.label}：移除第 {t.site!.removed_oxygen_index} 个原子（O），分数坐标 {t.site!.fractional.join(', ')}。</Typography.Text>)}
        {report.results.map(r => <Alert key={r.key} type="info" message={r.label+'：适用条件'} description={[...r.conditions,...r.unverified_conditions].join('；')}/>)}
        <Table size="small" rowKey="role" pagination={false} dataSource={report.inputs} columns={[
          {title:'输入',dataIndex:'role'},{title:'绑定任务',render:(_,i) => i.task?.model_name || '尚未选择'},
          {title:'能量 (eV)',render:(_,i) => i.data?.energy_ev ?? '—'},{title:'状态',dataIndex:'status',render:tag},
        ]}/>
        {report.not_calculable.length>0 && <Typography.Text>尚不能计算：{report.not_calculable.map(v=>v==='absolute_formation_energy'?'绝对氧空位形成能':v).join('；')}</Typography.Text>}
        <Table size="small" rowKey={(_,i) => String(i)} pagination={{pageSize:8}} dataSource={report.gaps} columns={[
          {title:'输入 / 校验',render:(_,g) => `${g.role || ''} ${g.check}`},{title:'状态',dataIndex:'status',render:tag},{title:'缺口与必要补证',dataIndex:'detail'},
        ]}/>
        <Collapse items={[
          {key:'sources',label:'逐项证据、目录、观测及验证依据',children:<pre style={{whiteSpace:'pre-wrap',maxHeight:500,overflow:'auto'}}>{JSON.stringify(report.inputs,null,2)}</pre>},
          {key:'suggestions',label:'必要补证与补算建议',children:report.supplemental_suggestions.map((s,i)=><div key={i}>{s.role} · {s.check}：{s.advice}</div>)},
          {key:'blocks',label:'可使用的报告元素',children:report.report_elements.map((b,i) => <div key={i}>{b.type} {b.task_id} {b.status && tag(b.status)} {b.note}</div>)},
        ]}/>
      </>}
    </Space>
  </Drawer>;
}
