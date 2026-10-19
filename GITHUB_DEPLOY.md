# DID Q&A — GitHub → Posit Connect 部署指南

这是 **Git-backed** 版本：把代码推到 GitHub 后，在 Posit Connect（RSC）里用 **Import from Git** 部署。之后每次 `git push`，Connect 会按仓库更新自动（或手动）重新部署。

对照参考：`C:\Users\lum16\Documents\Sigma_Search`（`manifest.json` + Git-Backed Content）。

当前 Connect 地址（本机已有一次 Publisher 部署记录）：`https://rsc.pfizer.com`

---

## 1. 必须推到 GitHub 的文件

| 文件 | 作用 |
|------|------|
| `manifest.json` | **关键。** Connect 靠它识别这是 FastAPI 应用，并安装依赖 |
| `app.py` | FastAPI 入口（`app:app`），提供 Insight2 UI 与 `/api/*` |
| `web/static/index.html` | DID Insight2 单页聊天界面 |
| `web/static/planning.js` / `planning.css` | Recommend Team / Allocate TLF People，沿用原有主题 |
| `planning_api.py` / `match_person.py` | 规划上传 API / 原有人名消歧 |
| `artifacts/*.joblib` / `provenance.json` | 四个原始 LFS 产物及 SHA-256 来源校验 |
| `agent.py` | 自然语言 → Cypher → 回答 |
| `neo4j_client.py` | Neo4j 只读查询 |
| `vox_client.py` | Vox GenAI OAuth + 对话 |
| `docs/` | DID 规则与 examples（用于 few-shot 提示） |
| `.github/agents/did-neo4j-qa.agent.md` | 可选：Copilot CLI agent 模板 |
| `requirements.txt` | Python 依赖 |
| `.python-version` | 指定 Python 3.11.1 |
| `.gitignore` | 防止把密钥和本地文件推上去 |
| `.rscignore` | CLI 发布时排除本地文件 |
| `.env.example` | 环境变量模板（不含密钥） |
| `README.md` | 项目说明 |
| `GITHUB_DEPLOY.md` | 本指南 |
| `start-local.bat` | 可选；仅本地测试用 |

仓库根目录结构应类似：

```
did-qa-rsc/                  # GitHub 仓库根目录
├── manifest.json            # 必须在「要部署的那个目录」里
├── app.py
├── agent.py
├── neo4j_client.py
├── vox_client.py
├── docs/
│   ├── skill.md
│   ├── schema.md
│   └── examples/*.md
├── .github/agents/did-neo4j-qa.agent.md
├── requirements.txt
├── .python-version
├── .gitignore
├── .rscignore
├── .env.example
├── README.md
├── GITHUB_DEPLOY.md
└── start-local.bat
```

如果仓库里还有别的项目，也可以把这些文件放在子目录（例如 `rsc-app/`）。Connect 会扫描含 `manifest.json` 的目录作为部署目标。

---

## 2. 绝对不要推到 GitHub 的文件

| 文件 / 目录 | 原因 |
|-------------|------|
| `.env` | 含 Neo4j 密码、Vox client secret |
| `.posit/` | 本地 Publisher 配置与部署记录 |
| `.venv/` / `venv/` | 虚拟环境 |
| `__pycache__/` | Python 缓存 |

`.gitignore` 已经排除了以上内容。推送前请再确认：

```powershell
git status
# 列表里不能出现 .env
```

---

## 3. 把文件推到 GitHub（Windows PowerShell）

以下在 **`rsc-app` 目录** 执行。请把 `YOUR_GITHUB_USER` 和仓库名改成你自己的。

### 3.1 在 GitHub 上建空仓库

1. 打开 GitHub（公司若用 Enterprise，用你们的 GitHub 地址）。
2. **New repository**
3. Repository name 建议：`did-qa-rsc`（或你喜欢的名字）
4. 选 **Private**（内部应用，不要公开）
5. **不要**勾选 Add a README / .gitignore / license（本地已有这些文件）
6. 点 **Create repository**
7. 复制仓库 HTTPS 地址，例如：
   - `https://github.com/YOUR_GITHUB_USER/did-qa-rsc.git`
   - 或公司 GitHub：`https://github.pfizer.com/YOUR_ORG/did-qa-rsc.git`

### 3.2 本地初始化并推送

在 PowerShell 中：

```powershell
cd "C:\Users\lum16\Documents\Neo4j\DID Agent\rsc-app"

# 确认不会提交密钥
Get-Content .env -ErrorAction SilentlyContinue | Select-Object -First 1
# 上面只是提醒：.env 必须存在于本机测试，但下一步 git add 不能包含它

git init -b main

git add app.py agent.py neo4j_client.py vox_client.py requirements.txt
git add docs\skill.md docs\schema.md docs\examples\*.md
git add .github\agents\did-neo4j-qa.agent.md
git add manifest.json .python-version .gitignore .rscignore .env.example
git add README.md GITHUB_DEPLOY.md start-local.bat

git status
# 确认：有 manifest.json 和源码；没有 .env、没有 .posit
```

如果 `git status` 里出现 `.env`，先停下来，检查 `.gitignore` 后再继续。

```powershell
git commit -m "Add Git-backed Posit Connect deployment for DID Q&A"

git remote add origin https://github.com/YOUR_GITHUB_USER/did-qa-rsc.git
git push -u origin main
```

若 GitHub 要求登录，用 **Personal Access Token** 当密码，或用 GitHub CLI / Git Credential Manager。

### 3.3 以后更新代码再部署

改完代码后：

```powershell
cd "C:\Users\lum16\Documents\Neo4j\DID Agent\rsc-app"

# 若增删了要打包的文件，重新生成 manifest.json（见第 6 节）
git add -A
git status          # 再次确认没有 .env
git commit -m "Describe your change"
git push origin main
```

然后在 Connect 上等自动刷新（默认约 15 分钟），或到该内容的 **Settings → Info** 点 **Update Now**。

---

## 4. 在 Posit Connect 上 Import from Git

需要 **Publisher** 及以上角色。

1. 打开 `https://rsc.pfizer.com`
2. **Content** → **Publish** → **Import from Git**
3. **Git repo URL**（必须是 **https://**，且 URL 里不要带用户名密码）：
   ```
   https://github.com/YOUR_GITHUB_USER/did-qa-rsc.git
   ```
4. 选分支：`main`
5. 选目标目录：Connect 会列出含 `manifest.json` 的目录。若文件在仓库根目录，选 `.`（或显示为仓库根）
6. 填写标题，例如：`DID Q&A`
7. 点 **Deploy Content**，看构建日志直到成功

Git-backed 内容在描述里会显示 **from Git**，并在 **Settings → Info** 看到 Git 元数据。

### 私有仓库

若仓库是 Private，Connect **服务器**上必须已配置该 Git 主机的凭据（`GitCredential.Host` / Username / Password）。  
这是管理员配置，不是把 token 写进仓库 URL。若 Import 报权限错误，请联系 RSC 管理员为 `github.com`（或你们的 GitHub Enterprise 主机）配置访问。

---

## 5. 在 Connect 上配置环境变量（必须）

**不要**把 `.env` 推到 GitHub。部署成功后，打开该内容 → **Vars**（或 Settings → Vars），添加：

| 变量 | 示例 / 说明 |
|------|-------------|
| `NEO4J_URI` | `bolt://10.109.2.157:7687` |
| `NEO4J_USERNAME` | `neo4j` |
| `NEO4J_PASSWORD` | （密钥） |
| `NEO4J_DATABASE` | `neo4j` |
| `VOX_GENAI_API` | `https://mule4api-comm-amer.pfizer.com/vox-genai-api-v2` |
| `VOX_TOKEN_GEN_URL` | `https://prodfederate.pfizer.com/as/token.oauth2` |
| `VOX_CLIENT_ID` | （密钥） |
| `VOX_CLIENT_SECRET` | （密钥） |
| `VOX_MODEL` | `gpt-4o` |

保存后重启该内容。Connect 服务器必须能访问 Neo4j Bolt 以及上述 Vox 地址。

---

## 6. 何时需要重新生成 `manifest.json`

Connect 用 `manifest.json` 里的文件清单和 checksum 来打包。下面情况需要重写它：

- 新增或删除了会被部署的文件
- 改了 `requirements.txt`

在本机（已安装 `rsconnect-python`）执行：

```powershell
cd "C:\Users\lum16\Documents\Neo4j\DID Agent\rsc-app"
# 在无密钥的独立 Git checkout 中执行；保留完整源码、静态资源和 artifacts
python -c "from rsconnect.main import cli; cli.main(args=['write-manifest','fastapi','--entrypoint','app:app','--overwrite','--exclude','.git/**','--exclude','.venv/**','--exclude','.artifact-cache/**','--exclude','.test-work/**','--exclude','data/**','--exclude','*.db','--exclude','*.sqlite*','.'])"
```

然后把更新后的 `manifest.json` 一并 commit / push。
此仓库以 `.gitattributes` 固定文本 LF；请在 LF checkout 生成 checksum，
避免 Windows CRLF 与 Connect 的 Git checkout 字节不一致。上面的调用把
排除模式直接传给 Click，避免 Windows 原生命令展开 `*`。

---

## 7. 限制（Git-backed）

- Git-backed 内容 **不能**再用 RStudio / Posit Publisher / `rsconnect deploy` 去覆盖同一条内容。
- Connect Git 导入通常仅拿到 LFS pointer。应用识别默认文件的 pointer 或缺失，
  从 **DID_QA_FastAPI** 自身固定 tag `published-artifacts-26af6b5` 下载完整字节，
  并按 `artifacts/provenance.json` 校验 SHA-256/大小，不依赖源仓库浮动 main。
  若 Git 导入对 LFS pointer checksum 报错，请在独立干净 checkout 执行
  `git lfs pull` 后发布新的 Connect 内容，或由管理员配置完整产物打包。
  原有 Git-backed 内容不可用 Publisher 强行覆盖。
- 构建需要 Python ≥3.11 / scikit-learn **1.9.1** / python-multipart / openpyxl。
  缓存目录必须可写；下载域名需要受信任证书。私有产物需要配置最小权限
  `GITHUB_TOKEN`。不要在代码或 manifest 写入真实凭据。
- 四个产物总计约 599 MiB；百万行人员快照需要足够的运行内存和首次预热时间。
  初次打开两个规划页会加载对应快照。仅发布 GitHub 不代表 Connect 已重新部署。
- 规划页采用提交任务 + 轮询，避免冷启动大工作簿超出 HTTP 代理超时。
  任务结果只存在内存，完成后一小时过期；Connect 应使用单 worker 或粘性路由。
  重启后重新提交即可；同步 `/api/planning/recommend`、`allocate` 仍可直接调用。
- Connect 对每个 Git 主机只支持一套凭据。

若仍想用 Publisher 一键发布，请新建另一条 Connect 内容，不要改这条 Git 内容。

---

## 8. 检查清单

推 GitHub 前：

- [ ] `manifest.json` 存在，且 `entrypoint` 为 `app:app`、`appmode` 为 `python-fastapi`
- [ ] 清单包含 `match_person.py`、规划 API、三个前端文件和四个原始产物
- [ ] `git status` 无 `.env`
- [ ] 仓库为 Private
- [ ] 远程 URL 无用户名/密码

Connect 上：

- [ ] Import from Git 构建成功
- [ ] Vars 已全部设置
- [ ] 从 Connect 能访问 Neo4j 与 Vox
- [ ] 打开应用能正常提问

---

**App**：DID Q&A（RSC / FastAPI）

**Python**：≥3.11；当前验证环境 3.13.0

**Connect**：https://rsc.pfizer.com
