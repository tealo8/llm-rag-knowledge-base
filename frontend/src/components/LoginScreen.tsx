import { useState } from "react";
import { BookOpenText, Building2, KeyRound, LoaderCircle, ShieldCheck } from "lucide-react";

interface LoginScreenProps {
  onLogin: (username: string, password: string) => Promise<void>;
  error: string;
}

const demoAccounts = [
  { label: "管理员", username: "admin", password: "admin123", detail: "全部资料与审计" },
  { label: "研发成员", username: "engineer", password: "engineer123", detail: "研发中心受限资料" },
  { label: "财务成员", username: "finance", password: "finance123", detail: "财务与行政资料" },
  { label: "另一租户", username: "otheradmin", password: "other123", detail: "星云数据空间" },
];

export function LoginScreen({ onLogin, error }: LoginScreenProps) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await onLogin(username, password);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-brand" aria-label="知域企业知识库">
        <div className="brand-lockup">
          <span className="brand-mark"><BookOpenText size={25} /></span>
          <span>知域</span>
        </div>
        <div className="login-brand-copy">
          <p className="eyebrow">企业知识工作台</p>
          <h1>让内部知识有边界地流动</h1>
          <p>统一检索文档，答案逐条引用来源，并在查询前执行组织、角色和用户组权限。</p>
        </div>
        <div className="login-trust-row">
          <span><ShieldCheck size={18} /> 权限前置</span>
          <span><Building2 size={18} /> 租户隔离</span>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-form-wrap">
          <div className="login-heading">
            <p className="eyebrow">安全访问</p>
            <h2>登录知识空间</h2>
            <p>使用企业账号继续</p>
          </div>
          <form onSubmit={submit} className="login-form">
            <label>
              <span>用户名</span>
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label>
              <span>密码</span>
              <div className="input-with-icon">
                <KeyRound size={17} />
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  required
                />
              </div>
            </label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="button primary login-submit" disabled={submitting}>
              {submitting ? <LoaderCircle className="spin" size={18} /> : <ShieldCheck size={18} />}
              登录
            </button>
          </form>

          <div className="demo-divider"><span>演示身份</span></div>
          <div className="demo-account-list">
            {demoAccounts.map((account) => (
              <button
                type="button"
                key={account.username}
                className={username === account.username ? "demo-account active" : "demo-account"}
                onClick={() => {
                  setUsername(account.username);
                  setPassword(account.password);
                }}
              >
                <span><strong>{account.label}</strong><small>{account.detail}</small></span>
                <code>{account.username}</code>
              </button>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}

