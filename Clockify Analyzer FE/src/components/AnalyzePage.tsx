import { useCallback, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Card,
  DatePicker,
  Form,
  Layout,
  Select,
  Space,
  Typography,
  Upload,
} from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { postAnalyze } from '../api/analyze'
import {
  DATE_FMT,
  rangeForPreset,
  type RangePreset,
} from '../lib/dateRange'

const { Header, Content } = Layout
const { Title } = Typography

type FormValues = {
  rangePreset: RangePreset
}

export function AnalyzePage() {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<FormValues>()
  const [leaveFile, setLeaveFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [lastResponse, setLastResponse] = useState<string | null>(null)
  const [customRange, setCustomRange] = useState<any>(null)
  const selectedPreset = Form.useWatch('rangePreset', form)
  const { RangePicker } = DatePicker

  const handleRunAnalyzer = useCallback(async () => {
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }

    const [start, end] = rangeForPreset(values.rangePreset)
    const startStr = start.format(DATE_FMT)
    const endStr = end.format(DATE_FMT)

    if (start.startOf('day').isAfter(end.startOf('day'))) {
      message.error('Start date must be on or before end date.')
      return
    }

    setSubmitting(true)
    setLastResponse(null)

    const result = await postAnalyze({
      startDate: startStr,
      endDate: endStr,
      writeExcel: true,
      leaveFile,
    })

    setSubmitting(false)

    if (!result.ok) {
      if ('error' in result) {
        message.error(result.error)
        return
      }
      message.error(`Request failed (${result.status})`)
      setLastResponse(result.bodyText)
      return
    }

    message.success('Analysis completed')
    try {
      const json = JSON.parse(result.bodyText) as unknown
      setLastResponse(JSON.stringify(json, null, 2))
    } catch {
      setLastResponse(result.bodyText)
    }
  }, [form, leaveFile, message])

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header
        style={{
          background: '#fff',
          borderBottom: '1px solid #f0f0f0',
          paddingInline: 24,
          display: 'flex',
          alignItems: 'center',
        }}
      >
        <Title level={3} style={{ margin: 0 }}>
          Clockify Analyzer 📊
        </Title>
      </Header>

      <Content
        style={{
          padding: 24,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
        }}
      >
        <Form<FormValues>
          form={form}
          layout="vertical"
          initialValues={{
            rangePreset: 'lastWeek',
          }}
          requiredMark={false}
          style={{ width: '100%', maxWidth: 400 }}
        >
          <Card
            style={{
              width: '100%',
              marginTop: 50,
              borderRadius: 12,
              boxShadow: '0 4px 20px rgba(0,0,0,0.05)',
            }}
          >
            <Space orientation="vertical" size="large" style={{ width: '100%' }}>
              <Form.Item
                name="rangePreset"
                label="Date range"
                rules={[{ required: true, message: 'Select a date range' }]}
              >
                <Select<RangePreset>
                  style={{ width: '100%' }}
                  options={[
                    { value: 'yesterday', label: 'Yesterday' },
                    { value: 'lastWeek', label: 'Last week' },
                    { value: 'custom', label: 'Custom range' },
                  ]}
                />
              </Form.Item>

              {selectedPreset === 'custom' && (
                <Form.Item
                  required
                  validateStatus={!customRange ? 'error' : ''}
                  help={!customRange ? 'Please select a date range' : ''}
                >
                  <RangePicker
                    style={{ width: '100%' }}
                    value={customRange}
                    onChange={(dates) => setCustomRange(dates)}
                  />
                </Form.Item>
              )}

              <Form.Item label="Leave requests (CSV)">
                <Upload
                  accept=".csv,text/csv"
                  maxCount={1}
                  beforeUpload={(file) => {
                    setLeaveFile(file)
                    return false
                  }}
                  onRemove={() => {
                    setLeaveFile(null)
                  }}
                  fileList={
                    leaveFile
                      ? [
                        {
                          uid: '-1',
                          name: leaveFile.name,
                          status: 'done',
                        },
                      ]
                      : []
                  }
                >
                  <Button icon={<UploadOutlined />} block>
                    Upload CSV
                  </Button>
                </Upload>
              </Form.Item>

              <Form.Item>
                <Button
                  type="primary"
                  size="large"
                  block
                  htmlType="button"
                  loading={submitting}
                  onClick={() => {
                    void handleRunAnalyzer()
                  }}
                >
                  Run Analyzer
                </Button>
              </Form.Item>
            </Space>
          </Card>
        </Form>

        {lastResponse ? (
          <Card
            style={{
              width: '100%',
              maxWidth: 400,
              marginTop: 24,
              borderRadius: 12,
              boxShadow: '0 4px 20px rgba(0,0,0,0.05)',
            }}
          >
            <Title level={5} style={{ marginTop: 0 }}>
              Last response
            </Title>
            <pre className="response-block">{lastResponse}</pre>
          </Card>
        ) : null}
      </Content>
    </Layout>
  )
}
