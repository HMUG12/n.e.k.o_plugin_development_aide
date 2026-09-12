/**
 * Development-Aide 设置面板
 * 作用：导入 Skill，并以只读模式读取项目文件，让猫娘/AI 做代码审查、错误定位和开发建议。
 */
import {
  Page,
  Card,
  Stack,
  Field,
  Input,
  Select,
  Switch,
  ActionButton,
  Text,
  Alert,
} from "@neko/plugin-ui"
import type { HostedAction, PluginSurfaceProps } from "@neko/plugin-ui"
import { useLocalState } from "@neko/plugin-ui"

type FeaturesEnabled = {
  code_review: boolean
  error_fix: boolean
  project_summary: boolean
  multi_file_summary: boolean
}

type State = {
  config: {
    skill_path: string
    workspace_root: string
    read_only: boolean
    max_chars: number
    analysis_tone: string
    default_file_extensions: string[]
    enable_code_review: boolean
    enable_error_fix: boolean
    enable_project_summary: boolean
    enable_multi_file_summary: boolean
  }
  status: {
    ready: boolean
    mode: string
    skill_loaded: boolean
    workspace_configured: boolean
    workspace_exists: boolean
    features_enabled: FeaturesEnabled
  }
}

const TONE_OPTIONS = [
  { label: "专业", value: "professional" },
  { label: "猫娘", value: "catgirl" },
]

// Same hard ceiling as the backend (MAX_CHARS_HARD_LIMIT).
const MAX_CHARS_HARD_LIMIT = 1_000_000

function isAbsolutePath(value: string): boolean {
  // POSIX absolute "/..." or Windows drive path "C:\..." / "C:/...".
  return /^(\/|[A-Za-z]:[\\/])/.test(value)
}

export default function SettingsPanel(props: PluginSurfaceProps<State>) {
  const { state, actions } = props

  // Cache actions so buttons do not flicker/disappear before actions load.
  const [cachedActions, setCachedActions] = useLocalState(
    "da-ca",
    () => [] as HostedAction[]
  )
  if (actions.length > 0 && actions.length !== cachedActions.length) {
    setCachedActions(actions)
  }
  const effectiveActions = cachedActions.length > 0 ? cachedActions : actions

  // ---- Local form state (issue #3: controls must be editable) -----------
  const [skillPath, setSkillPath] = useLocalState(
    "da-sp",
    () => state.config?.skill_path ?? ""
  )
  const [workspaceRoot, setWorkspaceRoot] = useLocalState(
    "da-wr",
    () => state.config?.workspace_root ?? ""
  )
  const [readOnly, setReadOnly] = useLocalState(
    "da-ro",
    () => state.config?.read_only ?? true
  )
  const [maxCharsText, setMaxCharsText] = useLocalState(
    "da-mc",
    () => String(state.config?.max_chars ?? 4000)
  )
  const [analysisTone, setAnalysisTone] = useLocalState(
    "da-at",
    () => state.config?.analysis_tone ?? "professional"
  )
  const [enableCodeReview, setEnableCodeReview] = useLocalState(
    "da-ecr",
    () => state.config?.enable_code_review ?? true
  )
  const [enableErrorFix, setEnableErrorFix] = useLocalState(
    "da-eef",
    () => state.config?.enable_error_fix ?? true
  )
  const [enableProjectSummary, setEnableProjectSummary] = useLocalState(
    "da-eps",
    () => state.config?.enable_project_summary ?? true
  )
  const [enableMultiFileSummary, setEnableMultiFileSummary] = useLocalState(
    "da-emf",
    () => state.config?.enable_multi_file_summary ?? true
  )

  const saveAction = effectiveActions.find((a: HostedAction) => a.id === "save_settings")
  const codeReviewAction = effectiveActions.find((a: HostedAction) => a.id === "generate_code_review")
  const errorFixAction = effectiveActions.find((a: HostedAction) => a.id === "generate_error_fix")
  const projectSummaryAction = effectiveActions.find((a: HostedAction) => a.id === "generate_project_summary")
  const multiSummaryAction = effectiveActions.find((a: HostedAction) => a.id === "generate_multi_file_summary")
  const quickAuditAction = effectiveActions.find((a: HostedAction) => a.id === "quick_audit")

  // ---- Validation --------------------------------------------------------
  const trimmedRoot = workspaceRoot.trim()
  const digits = maxCharsText.trim()
  const maxCharsValue = Number(digits)
  const maxCharsValid =
    /^\d+$/.test(digits) && maxCharsValue >= 1 && maxCharsValue <= MAX_CHARS_HARD_LIMIT
  const workspaceValid = trimmedRoot === "" || isAbsolutePath(trimmedRoot)
  const toneValid = analysisTone === "professional" || analysisTone === "catgirl"
  const formValid = maxCharsValid && workspaceValid && toneValid

  const workspaceStatus = state.status?.workspace_exists
    ? "工作区目录存在"
    : trimmedRoot
      ? "工作区目录不存在，请检查路径"
      : "尚未配置工作区目录"

  function buildConfig(): Record<string, unknown> {
    return {
      skill_path: skillPath.trim(),
      workspace_root: trimmedRoot,
      read_only: readOnly,
      max_chars: maxCharsValue,
      analysis_tone: analysisTone,
      enable_code_review: enableCodeReview,
      enable_error_fix: enableErrorFix,
      enable_project_summary: enableProjectSummary,
      enable_multi_file_summary: enableMultiFileSummary,
    }
  }

  const quickAuditEnabled =
    enableCodeReview || enableErrorFix || enableMultiFileSummary

  return (
    <Page title="Development-Aide">
      <Card title="开发辅助设置">
        <Stack>
          {!formValid ? (
            <Alert variant="error" title="设置校验未通过">
              {!maxCharsValid ? (
                <Text>单文件最大读取字符数必须是 1 ~ {MAX_CHARS_HARD_LIMIT} 之间的正整数。</Text>
              ) : null}
              {!workspaceValid ? <Text>工作区路径必须留空或填写绝对路径。</Text> : null}
              {!toneValid ? <Text>语气风格只能是“专业”或“猫娘”。</Text> : null}
            </Alert>
          ) : null}

          <Field label="已导入 Skill 路径（可选）">
            <Input
              value={skillPath}
              placeholder="例如 /home/you/.trae/skills/neko-plugin-dev"
              onChange={(v: string) => setSkillPath(v)}
            />
          </Field>

          <Field label={`项目工作区路径（绝对路径，留空则不启用读取）`}>
            <Input
              value={workspaceRoot}
              placeholder="例如 /home/you/projects/my-project 或 D:\\projects\\my-project"
              onChange={(v: string) => setWorkspaceRoot(v)}
            />
          </Field>
          <Text color="muted">{workspaceStatus}</Text>

          <Field label="语言/语气风格">
            <Select
              value={analysisTone}
              options={TONE_OPTIONS}
              onChange={(v: string) => setAnalysisTone(v)}
            />
          </Field>

          <Field label="只读模式（强烈建议保持开启）">
            <Switch checked={readOnly} onChange={(v: boolean) => setReadOnly(v)} />
          </Field>

          <Field label="单文件最大读取字符数">
            <Input
              value={maxCharsText}
              placeholder="4000"
              onChange={(v: string) => setMaxCharsText(v)}
            />
          </Field>

          <Card title="功能开关">
            <Stack>
              <Field label="代码审查入口">
                <Switch checked={enableCodeReview} onChange={(v: boolean) => setEnableCodeReview(v)} />
              </Field>
              <Field label="错误定位与修复建议">
                <Switch checked={enableErrorFix} onChange={(v: boolean) => setEnableErrorFix(v)} />
              </Field>
              <Field label="项目结构分析摘要">
                <Switch
                  checked={enableProjectSummary}
                  onChange={(v: boolean) => setEnableProjectSummary(v)}
                />
              </Field>
              <Field label="读取多文件后汇总建议">
                <Switch
                  checked={enableMultiFileSummary}
                  onChange={(v: boolean) => setEnableMultiFileSummary(v)}
                />
              </Field>
            </Stack>
          </Card>

          <Text color="muted">
            当前模式：仅读取已配置目录中的文件内容，不写入、重命名或删除文件；用于代码意见、调试指正与开发辅助建议。
            修改设置后请点击“保存设置”，功能按钮会按照已保存的开关状态启用或停用。
          </Text>

          {saveAction && formValid ? (
            <ActionButton action={saveAction} values={{ config: buildConfig() }}>
              保存设置
            </ActionButton>
          ) : (
            <Text color="muted">
              {formValid ? "保存按钮加载中…" : "请先修正上方设置错误，再保存。"}
            </Text>
          )}
        </Stack>
      </Card>

      <Card title="分析操作">
        <Stack>
          {codeReviewAction && enableCodeReview ? (
            <ActionButton action={codeReviewAction} values={{}}>
              代码审查
            </ActionButton>
          ) : (
            <Text color="muted">代码审查（已在功能开关中关闭）</Text>
          )}

          {errorFixAction && enableErrorFix ? (
            <ActionButton action={errorFixAction} values={{}}>
              修复建议
            </ActionButton>
          ) : (
            <Text color="muted">修复建议（已在功能开关中关闭）</Text>
          )}

          {projectSummaryAction && enableProjectSummary ? (
            <ActionButton action={projectSummaryAction} values={{}}>
              结构摘要
            </ActionButton>
          ) : (
            <Text color="muted">结构摘要（已在功能开关中关闭）</Text>
          )}

          {multiSummaryAction && enableMultiFileSummary ? (
            <ActionButton action={multiSummaryAction} values={{}}>
              多文件汇总
            </ActionButton>
          ) : (
            <Text color="muted">多文件汇总（已在功能开关中关闭）</Text>
          )}

          {quickAuditAction && quickAuditEnabled ? (
            <ActionButton action={quickAuditAction} values={{}}>
              一键开发审查
            </ActionButton>
          ) : (
            <Text color="muted">一键开发审查（审查/修复/多文件汇总均已关闭）</Text>
          )}
        </Stack>
      </Card>
    </Page>
  )
}
