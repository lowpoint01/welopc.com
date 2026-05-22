# AI Signal Radar

这是 AI 每日信号的静态站点壳子。自动化任务每次执行 `ai-news-schedule-run` 时会更新：

- `data/latest.json`
- `data/history.json`
- `data/latest.md`

免费部署方式：

1. GitHub Pages
   将 `D:\Agent\电商调研\site\ai-signal-live` 作为发布目录。
2. Cloudflare Pages
   推荐用 Direct Upload，而不是 Git 集成。原因是站点数据由本机自动化持续生成，不需要把 `latest.json` 每次提交回仓库。
3. Vercel
   选择静态站点，无需构建命令，输出目录填 `site/ai-signal-live`。

如果要本地预览：

```powershell
cd D:\Agent\电商调研\site\ai-signal-live
python -m http.server 8765
```

## Cloudflare Pages

官方部署口径：

- 静态站点可以不填构建命令，直接上传构建输出目录
  参考：[Build configuration](https://developers.cloudflare.com/pages/configuration/build-configuration/)
- 这类由本地自动化生成的静态目录，更适合用 Direct Upload
  参考：[Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)
- 持续部署时可以直接运行：
  `CLOUDFLARE_ACCOUNT_ID=<ACCOUNT_ID> npx wrangler pages deploy <DIRECTORY> --project-name=<PROJECT_NAME>`
  参考：[Use Direct Upload with continuous integration](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/)

建议的接法：

1. 在 Cloudflare Dashboard 先创建一个 Pages 项目
2. 项目名建议用 `ai-signal-radar`
3. 生产分支随便填一个占位名，例如 `main`
4. 在本机持久环境变量里设置：

```powershell
setx CLOUDFLARE_ACCOUNT_ID "你的 account id"
setx CLOUDFLARE_API_TOKEN "你的 Cloudflare API token"
setx CLOUDFLARE_PAGES_PROJECT "ai-signal-radar"
```

如果你要把部署打到预览分支，而不是生产环境，再额外设置：

```powershell
setx CLOUDFLARE_PAGES_BRANCH "preview"
```

这套自动化脚本现在会在站点窗口命中后自动执行：

```powershell
npx wrangler pages deploy D:\Agent\电商调研\site\ai-signal-live --project-name=ai-signal-radar
```

Cloudflare API Token 权限至少需要：

- `Account`
- `Cloudflare Pages`
- `Edit`

官方说明见：
[Use Direct Upload with continuous integration](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/)
[Wrangler system environment variables](https://developers.cloudflare.com/workers/wrangler/system-environment-variables/)
