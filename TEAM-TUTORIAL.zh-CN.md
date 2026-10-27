# reel-crawler · 团队审阅使用教程（中文版）

实验室需要的全部内容：采集 Instagram reels、模型筛选、**每位成员审阅每一条视频**——所有意见都保留，并通过一个 private GitHub 仓库全组同步。

- **新成员？** 先看一页速览 [ONBOARDING.md](ONBOARDING.md)（英文），然后从 [2. 环境要求](#2-环境要求) 开始，按 [4. 加入你的机器](#4-加入你的机器) 操作。
- **今天只想审阅？** 直接看 [5. 每日流程——审阅](#5-每日流程审阅)。
- **喜欢命令行？** 每个页面操作都有对应的 CLI 命令，见 [6. 命令行对照表](#6-命令行对照表)。

> 英文原版：TEAM-TUTORIAL.md（内容一致）

---

## 1. 团队工作流总览

```
采集                    筛选（可选，按实验室政策）              审阅
──────────             ────────────────────────────          ──────
feed_collector.py  →   feed_collector.py --rescreen（LLM） →   review_gui.py
每位成员一个              点赞门槛 + 音频 + 视觉模型             每位成员
Instagram 账号                                                审每一条视频
        │                                                              │
        └────────────  sync_repo/（private GitHub 仓库）  ─────────────┘
                         items/  opinions/  accounts/
```

- **items** = 每条采集视频的公开元数据（URL、@作者、点赞数、文案、模型判断）。视频本体、抽帧、转录**永不离开本机**——IRB 规定（视频可能含第三方人脸）。
- **opinions** = 每位审阅者一份 append-only 日志。每个决定永久保留，包括互相冲突的；有争议的视频自动列表。
- **accounts** = 每位成员的用户名+密码（只存加盐 PBKDF2 哈希）。全组可以**共用一个 GitHub 账号**——成员靠应用内账号区分，且每条 git commit 的作者都写成该账号名。不需要把组员加成 GitHub collaborator。

## 2. 环境要求

| 要求 | 说明 |
|---|---|
| Python 3 | 审阅工具只用标准库 |
| git | macOS 自带（Xcode CLT）/ 任意 Linux 发行版 |
| 浏览器 | 工具页面是本地网页（Edge/Chrome） |
| 一个 **private** GitHub 仓库 | 只建一次（第 3 节）；归任意单一账号（如实验室公用账号） |

只有**采集和筛选**的机器才需要采集器的依赖（Playwright + cookies，视觉模型还要 Ollama）——详见 RUNBOOK.md。审阅什么都不用装。

## 3. 一次性配置（第一台机器，约 5 分钟）

### 3.1 在 GitHub 上建 private 仓库

1. 登录持有同步仓库的账号（一个实验室公用账号即可）。
2. **New repository** → 命名如 `reel-review-sync` → 选 **Private** → 不要勾 "Add a README"（仓库必须从空开始）→ Create。
3. （共用账号路线）给它建一个 **token**：Settings → Developer settings → Personal access tokens → 权限只勾 `repo`。复制 token——每台机器粘贴一次，之后不再显示。
   （个人凭据路线：跳过 token，用每台机器自己的 GitHub 身份，如 SSH。两条路线都可用。）

### 3.2 在第一台机器启动团队中心

```bash
cd reel-crawler
python3 team_gui.py        # 或：python3 review_team.py gui
```

浏览器自动打开 **http://127.0.0.1:8766**——团队中心。从上到下填卡片：

**1 · Shared GitHub repo（共享仓库）**
粘贴仓库 URL（`https://github.com/<账号>/reel-review-sync`），走共用账号路线再粘贴 token。点 **Set up / update remote**。这会在本地创建 `sync_repo/` 文件夹、提交初始状态并推送到 GitHub。之后 URL 和 token 只记在这台机器本地（工具目录旁的隐藏文件 `.hub_credentials.json`，绝不上传），下次打开团队中心会自动填好；想清除就点 **Clear saved URL & token**。

**2 · Member accounts（成员账号）**
给每位成员建账号：用户名+密码（至少 4 位）。密码只以加盐 PBKDF2 哈希形式存储并同步到 GitHub——明文永不离开本机。表格显示每个人的审阅进度。

**3 · Log in（登录）**
用你自己的账号登录——团队中心会先核对密码，再从 GitHub 拉取最新共享状态，你的审阅队列因此永远最新。勾选 "Open the review queue right after login" 的话，审阅页（http://127.0.0.1:8765）会在准备就绪后自动打开。注意：**勾选框只在未登录的登录表单里出现**——已经登录时，卡片 3 显示的是 **Open review queue →** 按钮，点它效果完全一样；页面顶部也常驻同一个按钮。如果浏览器拦截了自动弹窗，点这个按钮即可——手动链接永远有效。

**6 · Add videos to the pool（往池子里加视频）**
任何成员都可以给全组递视频：把 reel 链接一行一个粘进卡片 6，点 **Add to the pool**。这些视频在每位成员下次 pull 后自动进入他们的审阅队列——完全不需要跑采集器。只共享公开元数据（URL、@作者、点赞数、文案）；作者 / 文案 / 点赞数可选，且同一次对所有行生效。适用于团队在采集器之外拿到的视频，比如从本地下载的文件里挑出来的。

**7 · Collect new reels（采集新视频）**
采集器变成了三步清单。每位成员都可以从自己电脑上找新视频：依次打勾（1）采集器依赖、（2）Instagram 登录（用干净账号——feed 没被训练成单一主题的）、（3）团队登录——然后设定采多少条、每条在屏幕上停留多少秒，最底下的 **Start collection** 按钮就会亮起。之后采集器全自动驾驶：自动刷 feed、每条视频停留同样固定时长、保存 frame info，并把视频推进全员的审阅队列。卡片上有实时日志显示进度，随时可以 **Stop**。详见第 5 节。

配置到此结束。其余卡片每天用（第 5 节）。

## 4. 加入你的机器

每位成员先在自己机器上拿到工具代码（就是包含本文件的仓库），然后：

```bash
cd reel-crawler
python3 team_gui.py
```

1. **卡片 1**——粘贴同一个仓库 URL（共用账号路线再粘 token）。团队中心检测到仓库已有历史，会**自动 clone** 而不是新建。首次设置成功后，这两个字段就记在这台机器上，以后每次打开都自动填好。
2. **卡片 3**——用**你自己的**账号密码登录。

别的什么都不用做：你的审阅队列 = 整个视频池减去你已经审过的。

## 5. 每日流程——审阅

```bash
python3 team_gui.py            # 打开团队中心
```

- **卡片 4 · Sync**——开审前点 **Sync: online → this machine**（登录时也会自动拉），拿到昨天以来所有人采集和审阅的内容；**Sync: this machine → online** 把你本机的改动传上去——既包括你的审阅意见，也包括本地采集库里的新视频元数据（视频本体永不离开本机）。
- **卡片 3**——点 **Open review queue**（或登录时勾选自动打开）。
- 审阅页像考试卷一样：
  - 左侧**侧边栏**列出所有视频，分成**未标注（Not decided yet）**和**已标注（Decided）**两栏——点任意一条直接跳到那个视频。
  - **← Prev / Next →**（键盘 `p` / `n` 或 `↑` / `↓`）在整张列表里前后走动，可以先跳过、稍后再回来——列表循环滚动：过了最后一条回到第一条，在最顶往上回到最后一条。
  - 键盘：

  | 键 | 功能 |
  |---|---|
  | `g` | 通过（保留模型的分类） |
  | `w` | 拒绝 |
  | `r` | 选分类（`1`–`12`）并通过 |
  | `u` | 撤销上一个决定 |
  | `p` / `n`、`↑` / `↓` | 上一个 / 下一个视频（到头循环） |
  | `s` | 一键提交全部决定 |
  | `←`/`→` | 切换抽帧焦点 |

  决定**先只存在本机**——按 **Submit**（`s`）时一次性全部上传。提交前随时可以回侧边栏改之前的答案（以最后一次为准，每次修改都留痕）。抽帧不足 10 张（含 0 张）的条目会出现 **Capture 10 frames from link** 按钮——按下即下载该 reel 并按视频时长均匀切出 10 帧，存在本机 `review_frames/` 下；也可以直接点开 reel 链接看视频本身再决定。
- 队列空了 = 你把整个池审完了。进度对全员可见（卡片 2，或 `python3 review_team.py status`）。
- **在别处找到了视频？** 用卡片 6（或下面的 `pool add`）把它们放进全员队列，再点一次 **Sync · push** 让大家都看到。卡片 6 的 **Fix metadata** 区可以手工给池里的视频写回作者 / 点赞数 / 文案——查不到时手动补（每次采集跑完后也会自动补采这些）。

### 找新视频进池（任何成员，可选）

最简单的方式是团队中心的**卡片 7 · Collect new reels**——一条命令（`python3 review_team.py collect`，或 `python3 team_gui.py` 后往下滚）打开清单：

1. **Collector dependencies（采集器依赖）**——没打勾时卡片会显示需要跑的那一条命令（`pip install -r requirements.txt`），装完点 **Re-check**。
2. **Instagram login（Instagram 登录）**——点 **Open Instagram login**：弹出浏览器窗口打开 Instagram，你手动登录（用干净账号——feed 没被训练成单一主题的），登录一被检测到会话就自动保存——勾自己会出现。
3. **Team login（团队登录）**——用你自己的账号登录（卡片上直接登录，或卡片 3）；池里你的贡献就以这个名字署名。

然后设定采多少条、每条视频在屏幕上停留多少秒（固定停留——每条视频得到同样的观看时长），按 **Start collection**——三个勾全绿按钮才会亮。之后采集器全自动驾驶：自动刷 feed、结束时保存 frame info，并把视频推进全员的审阅队列。跑完以后它还会自动做两件事：

- **给每条新视频抓 10 帧**——审阅队列立刻就有抽帧证据，不需要额外步骤。
- **补采缺失的 author / likes**——池里作者或点赞数不明的视频（比如手工加链接进来的）会被自动重新查一遍（不开浏览器、不碰 feed），补齐元数据。

进度看卡片上的实时日志，随时可以 **Stop**。没同步成功的采集结果（比如断网）会留在本机，下一次成功同步时一起上传——不会丢。

喜欢命令行？同样的步骤就是几条命令：

```bash
pip install -r requirements.txt && playwright install chromium   # 一次性
python3 feed_collector.py --login          # 打开 Instagram，登录后自动保存
python3 review_team.py login <名字>        # 团队账号
python3 feed_collector.py --target 100 --output feed_candidates_mine
python3 feed_collector.py --rescreen --target 100 --output feed_candidates_mine --llm off
```

只想手工挑几条？用卡片 6 / `pool add` 即可——采集器负责从 feed 批量发现新视频。采集器与筛选细节见 RUNBOOK.md；开跑前先读 README.md 的采集纪律（账号卫生、固定停留时间）。

## 6. 命令行对照表

团队中心就是 `review_team.py` 的图形界面；所有功能在终端同样可用（可脚本化，SSH 远程也方便）：

| 任务 | 命令 |
|---|---|
| 初始化同步仓库（第一台机器） | `python3 review_team.py init https://github.com/<账号>/reel-review-sync` |
| 其他机器加入 | `git clone <仓库URL> sync_repo` |
| 建账号 | `python3 review_team.py account add <名字>` |
| 列账号 | `python3 review_team.py account list` |
| 登录 / 登出 | `python3 review_team.py login <名字>` · `logout` |
| 拉取 / 推送团队状态 | `python3 review_team.py sync pull` · `sync push` |
| 全员进度 | `python3 review_team.py status` |
| 争议视频（表格） | `python3 review_team.py disputes` |
| 打印合并池 | `python3 review_team.py pool` |
| 往池子里加视频（全员可见） | `python3 review_team.py pool add <reel链接> [<更多链接>] [--username @作者] [--caption 文案] [--likes 点赞数]` |
| 手工改一条池视频的作者 / 点赞 | `python3 review_team.py pool edit <短码> [--username @作者] [--likes 点赞数] [--caption 文案]` |
| 自动补采缺失的作者 / 点赞 | `python3 review_team.py pool enrich [<短码>]`（不给短码 = 补齐池里所有缺作者或缺点赞的视频） |
| 打开团队中心 | `python3 review_team.py gui` |
| 打开团队中心并直接到采集卡片 | `python3 review_team.py collect` |
| 审阅队列（团队模式） | `python3 review_gui.py` |
| 为一条 reel 抓 10 帧 | `python3 review_capture.py --url <reel链接>` |
| 为池中所有缺帧视频抓 10 帧 | `python3 review_capture.py --pool` |

## 7. 账号与密码

- 用户名：字母、数字、点、横杠、下划线（最长 32）。
- 密码：至少 4 位。以加盐 PBKDF2-SHA256（120 000 次迭代）存于 `sync_repo/accounts/<名字>.json`——只写哈希、只同步哈希。
- 改密码：团队中心 → 卡片 3 → **Change my password**。
- 故意不提供删号：删号会让该成员的历史意见失去归属。需要删找工具维护者。

## 8. 进度、争议与数据

- **进度**：团队中心卡片 2，或 `status`。每人的 `done / total`，以及还没人审过的视频数。
- **争议**：团队中心卡片 5，或 `disputes`。审阅者意见不一致（通过 vs 拒绝，或分类不同）即列为争议。所有意见都保留在文件里，表格只是把冲突摆出来。
- **文件位置**：

  | 路径 | 内容 |
  |---|---|
  | `sync_repo/accounts/` | 成员账号（仅哈希） |
  | `sync_repo/items/<名字>.jsonl` | 每位成员的视频元数据（采集或手动添加） |
  | `sync_repo/opinions/<名字>.jsonl` | 每位审阅者的决定，append-only |
  | `sync_repo/pool.json` | 合并池（派生文件，不入库） |
  | `sync_repo/.session.json` | 本机登录者（不入库） |
  | `.hub_credentials.json`（在 `sync_repo/` 外面） | 本机记住的仓库 URL + token（绝不上传） |
  | `feed_candidates*/` | 本地采集存储（永不提交） |
  | `review_frames/`、`review_videos/` | 本地抽帧证据 / 下载（永不提交） |

## 9. 常见问题

**设置按钮提示 "could not reach the remote"（连不上远端）**
token 错、URL 错或没网。token 权限必须含 `repo`；URL 必须完全一致（区分大小写）；本机能直连 GitHub（工具已自动剥离失效的代理变量）。

**登录提示 "could not pull yet"（拉不下来）**
本机连不上 GitHub。离线也能审——决定先写在本地，下次 pull/push 成功时补推（审阅队列每次决定都会重试推送）。

**两个人同时推送冲突**
每次推送前都会先 rebase 拉取；冲突的推送会失败并在下一次决定时重试。最坏情况是多按一次按键——意见是 append-only 的，不会丢。

**登录后审阅页没打开**
浏览器可能拦截了自动弹窗——点 **Open review queue →**（卡片 3 或页面顶部）即可，手动链接永远有效，必要时会在当前标签页打开。团队中心现在也会等审阅页服务器真正就绪才打开它，不会再出现空白标签页。

**我审过的视频显示还没审**
点 **Sync · pull**——页面显示的是本地状态，pull 之后才会包含所有人的最新推送。

**组员需要是同步仓库的 GitHub collaborator 吗？**
不需要——共用账号路线下所有人用同一个 token 推送；SSH 路线下把每台机器的公钥加到那个 GitHub 账号上。无论哪种，仓库只需要**一个** GitHub 账号。

**没有 GitHub 账号能用吗？**
能，但同步变手动：`sync_repo/` 就是个 git 仓库，推/拉到任何 git 主机（GitLab、实验室服务器、U 盘）完全一样——只改 URL。
