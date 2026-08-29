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
} from "@neko/plugin-ui"
import type { HostedAction, PluginSurfaceProps } from "@neko/plugin-ui"

type State = {
  config: {
    skill_path: string
    workspace_root: string
    read_only: boolean
    max_chars: number
    analysis_tone: string
    enable_code_review: boolean
    enable_error_fix: boolean
    enable_project_summary: boolean
    enable_multi_file_summary: boolean
  }
  status: {
    ready: boolean
    mode: string
    skill_loaded: boolean
    features_enabled: {
      code_review: boolean
      error_fix: boolean
      project_summary: boolean
      multi_file_summary: boolean
    }
  }
}

export default function SettingsPanel(props: PluginSurfaceProps<State>) {
  const { state, actions } = props
  const saveAction = actions.find((a: HostedAction) => a.id === "save_settings")
  const codeReviewAction = actions.find((a: HostedAction) => a.id === "generate_code_review")
  const errorFixAction = actions.find((a: HostedAction) => a.id === "generate_error_fix")
  const projectSummaryAction = actions.find((a: HostedAction) => a.id === "generate_project_summary")
  const multiSummaryAction = actions.find((a: HostedAction) => a.id === "generate_multi_file_summary")
  const quickAuditAction = actions.find((a: HostedAction) => a.id === "quick_audit")

  const skillPath = state.config?.skill_path ?? "/home/codespace/.trae/skills/neko-plugin-dev"
  const workspaceRoot = state.config?.workspace_root ?? "/workspaces/n.e.k.o_plugin_Development-Aide"
  const readOnly = state.config?.read_only ?? true
  const maxChars = state.config?.max_chars ?? 4000
  const analysisTone = state.config?.analysis_tone ?? "professional"
  const enableCodeReview = state.config?.enable_code_review ?? true
  const enableErrorFix = state.config?.enable_error_fix ?? true
  const enableProjectSummary = state.config?.enable_project_summary ?? true
  const enableMultiFileSummary = state.config?.enable_multi_file_summary ?? true

  return (
    <Page title="Development-Aide">
      <Card title="开发辅助设置">
        <Stack>
          <Field label="已导入 Skill 路径">
            <Input value={skillPath} placeholder="/home/codespace/.trae/skills/neko-plugin-dev" />
          </Field>

          <Field label="项目工作区路径">
            <Input value={workspaceRoot} placeholder="/workspaces/your-project" />
          </Field>

          <Field label="语言/语气风格">
            <Select
              value={analysisTone}
              options={[
                { label: "专业", value: "professional" },
                { label: "猫娘", value: "catgirl" },
              ]}
            />
          </Field>

          <Field label="只读模式">
            <Switch checked={readOnly} />
          </Field>

          <Field label="单文件最大读取字符数">
            <Input value={String(maxChars)} placeholder="4000" />
          </Field>

          <Card title="功能开关">
            <Stack>
              <Field label="代码审查入口">
                <Switch checked={enableCodeReview} />
              </Field>
              <Field label="错误定位与修复建议">
                <Switch checked={enableErrorFix} />
              </Field>
              <Field label="项目结构分析摘要">
                <Switch checked={enableProjectSummary} />
              </Field>
              <Field label="读取多文件后汇总建议">
                <Switch checked={enableMultiFileSummary} />
              </Field>
            </Stack>
          </Card>

          <Text>
            当前模式：仅读取已配置目录中的文件内容，不写入、重命名或删除文件；用于为用户提供代码意见、调试指正与开发辅助建议。
          </Text>

          {saveAction ? (
            <ActionButton action={saveAction} values={{}}>
              保存设置
            </ActionButton>
          ) : null}

          <Stack>
            {codeReviewAction ? (
              <ActionButton action={codeReviewAction} values={{}}>
                代码审查
              </ActionButton>
            ) : null}
            {errorFixAction ? (
              <ActionButton action={errorFixAction} values={{}}>
                修复建议
              </ActionButton>
            ) : null}
            {projectSummaryAction ? (
              <ActionButton action={projectSummaryAction} values={{}}>
                结构摘要
              </ActionButton>
            ) : null}
            {multiSummaryAction ? (
              <ActionButton action={multiSummaryAction} values={{}}>
                多文件汇总
              </ActionButton>
            ) : null}
            {quickAuditAction ? (
              <ActionButton action={quickAuditAction} values={{}}>
                一键开发审查
              </ActionButton>
            ) : null}
          </Stack>
        </Stack>
      </Card>
    </Page>
  )
}
