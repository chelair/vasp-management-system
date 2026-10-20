import { useEffect, useState } from 'react';
import { Alert, App, Button, Descriptions, Modal, Space, Spin } from 'antd';
import { request } from '../../api/client';

interface Review {
  job_id: string; directory: string; checked_at: string; review_fingerprint: string;
  lsf_status: string; already_confirmed: boolean; blocker: string; can_confirm: boolean; note: string;
  receipts: {directory: string; file: string; text: string}[]; receipt_error: string; confirmation_summary: string;
}

export default function PriorJobReviewDialog({taskId, onClose}: {taskId: string; onClose: () => void}) {
  const {message} = App.useApp();
  const [busy, setBusy] = useState(true);
  const [review, setReview] = useState<Review>();
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const root = `/agent-execution/tasks/${encodeURIComponent(taskId)}/prior-job`;
  useEffect(() => {
    let cancelled = false;
    setBusy(true); setError(''); setReview(undefined);
    request<Review>(root).then(value => {if (!cancelled) setReview(value);})
      .catch(e => {if (!cancelled) setError(e instanceof Error ? e.message : String(e));})
      .finally(() => {if (!cancelled) setBusy(false);});
    return () => {cancelled = true;};
  }, [root, refresh]);
  const save = async () => {
    if (!review?.can_confirm || !review.confirmation_summary) return;
    setBusy(true); setError('');
    try {
      await request(root + '/confirm-finished', {method: 'POST', body: JSON.stringify({
        confirmed_finished: true, expected_job_id: review.job_id, review_fingerprint: review.review_fingerprint,
        evidence: review.confirmation_summary,
      })});
      void message.success('旧作业阻塞已解除；未提交新作业。可重新点击提交作业。');
      onClose();
    } catch (e) {setError(e instanceof Error ? e.message : String(e));}
    finally {setBusy(false);}
  };
  return <Modal open title="原作业结束状态需确认" width={760} onCancel={() => !busy && onClose()} maskClosable={false}
    footer={<Space><Button disabled={busy} onClick={onClose}>暂不处理</Button>
      <Button disabled={busy} onClick={() => setRefresh(value => value + 1)}>重新核对</Button>
      <Button type="primary" loading={busy} disabled={!review?.can_confirm || !review.confirmation_summary}
        onClick={() => void save()}>确认旧作业已结束并解除报错</Button></Space>}>
    <Spin spinning={busy}>
      {error && <Alert type="error" message={error} showIcon/>}
      {review && <Space direction="vertical" style={{width: '100%'}}>
        <Alert type="warning" message={review.note} showIcon/>
        <Descriptions size="small" column={1} items={[
          {key:'job',label:'旧作业号',children:review.job_id || '无'},
          {key:'state',label:'LSF状态',children:review.lsf_status === 'NOT_FOUND' ? '历史记录不可查' : review.lsf_status},
          {key:'dir',label:'任务目录',children:review.directory},
          {key:'at',label:'本次查询时间',children:review.checked_at},
        ]}/>
        {review.blocker && <Alert type="error" message={review.blocker} showIcon/>}
        {review.already_confirmed && <Alert type="success" message="此旧作业已有人工结束确认，可关闭窗口重试；提交时仍会检查活跃作业。"/>}
        {review.confirmation_summary && <Alert type="info" message={review.confirmation_summary}/>}
        {review.receipts.map((receipt, index) => <details key={receipt.directory} open={index === 0}>
          <summary>LSF回执：{receipt.directory}/{receipt.file}</summary>
          <pre style={{whiteSpace:'pre-wrap',maxHeight:300,overflow:'auto',fontSize:12}}>{receipt.text}</pre>
        </details>)}
        {!review.confirmation_summary && !review.blocker && !review.already_confirmed &&
          <Alert type="info" message={review.receipt_error || '现有回执不足以核实该作业身份、目录和结束时间，不能直接解除，请人工进一步核实。'}/>}
      </Space>}
    </Spin>
  </Modal>;
}
