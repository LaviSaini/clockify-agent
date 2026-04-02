import { App as AntdApp, ConfigProvider } from 'antd'
import { AnalyzePage } from './components/AnalyzePage'

export default function App() {
  return (
    <ConfigProvider>
      <AntdApp>
        <AnalyzePage />
      </AntdApp>
    </ConfigProvider>
  )
}
