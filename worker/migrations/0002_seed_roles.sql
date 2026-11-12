-- 内置权限与角色种子数据；自定义角色由管理台写入，不在此文件。

INSERT OR IGNORE INTO permissions (code, description) VALUES
  ('record:read',   '查看下发记录'),
  ('record:write',  '创建/上传下发记录'),
  ('record:delete', '删除下发记录'),
  ('cert:deliver',  '执行证书下发'),
  ('user:read',     '查看用户'),
  ('user:write',    '创建/修改用户'),
  ('role:write',    '管理角色与权限'),
  ('audit:read',    '查看审计日志'),
  ('policy:write',  '修改站点策略'),
  ('apiclient:write','管理投递客户端');

INSERT OR IGNORE INTO roles (id, name, description, builtin, created_at) VALUES
  ('super_admin', 'super_admin', '超级管理员：全部权限', 1, datetime('now')),
  ('admin',       'admin',       '管理员：记录、用户、审计', 1, datetime('now')),
  ('operator',    'operator',    '操作员：上传与下发', 1, datetime('now')),
  ('auditor',     'auditor',     '审计员：只读记录与审计', 1, datetime('now')),
  ('user',        'user',        '普通用户：查看自己的记录', 1, datetime('now')),
  ('readonly',    'readonly',    '只读访客', 1, datetime('now'));

INSERT OR IGNORE INTO role_permissions (role_id, permission_code) VALUES
  ('super_admin','record:read'), ('super_admin','record:write'), ('super_admin','record:delete'),
  ('super_admin','cert:deliver'), ('super_admin','user:read'), ('super_admin','user:write'),
  ('super_admin','role:write'), ('super_admin','audit:read'), ('super_admin','policy:write'),
  ('super_admin','apiclient:write'),

  ('admin','record:read'), ('admin','record:write'), ('admin','record:delete'),
  ('admin','cert:deliver'), ('admin','user:read'), ('admin','user:write'),
  ('admin','audit:read'), ('admin','apiclient:write'),

  ('operator','record:read'), ('operator','record:write'), ('operator','cert:deliver'),

  ('auditor','record:read'), ('auditor','audit:read'),

  ('user','record:read'),

  ('readonly','record:read');
