import { useEffect, useState } from 'react';
import { App, Button, Form, Input, Skeleton } from 'antd';
import { fetchServers } from '../../api/projects';
import { fetchRootPaths, saveRootPaths } from '../../api/settings';
import type { ServerOption } from '../../types';

/** 项目根目录配置：本地 + 各服务器远端，修改后整体重定位，任务路径保持相对 */
export default function RootPathsCard({ onSaved }: { onSaved?: () => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [servers, setServers] = useState<ServerOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([fetchRootPaths(), fetchServers()])
      .then(([m, sv]) => {
        setServers(sv);
        form.setFieldsValue({
          local_root: m.local_root,
          remote_roots: m.remote_roots,
        });
      })
      .catch(() => message.error('读取根目录配置失败'))
      .finally(() => setLoading(false));
  }, [form, message]);

  const save = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const remote = values.remote_roots ?? {};
      for (const s of servers) {
        if (remote[s.name] === undefined) remote[s.name] = '';
      }
      await saveRootPaths({
        local_root: values.local_root,
        remote_roots: remote,
      });
      message.success('项目根目录已保存，任务路径自动重定位');
      onSaved?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="ssh-path-settings">
      {loading ? (
        <Skeleton active paragraph={{ rows: 3 }} />
      ) : (
        <Form form={form} layout="vertical">
          <p>统一设置项目文件的存放位置。修改根目录会更新任务路径，请先确保文件已位于新目录。</p>
          <Form.Item
            label="本地项目根目录"
            name="local_root"
            rules={[{ required: true, message: '请输入本地根目录' }]}
          >
            <Input placeholder="如 D:/vasp_projects" />
          </Form.Item>
          {servers.map((s) => (
            <Form.Item
              key={s.name}
              label={`远程根目录 · ${s.name}（${s.user}@${s.host}）`}
              name={['remote_roots', s.name]}
            >
              <Input placeholder="如 /data/gpfs03/mdye/projects/test" />
            </Form.Item>
          ))}
          <Button type="primary" loading={saving} onClick={() => void save()}>
            保存根目录
          </Button>
        </Form>
      )}
    </div>
  );
}
