import { useState, useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { Button } from '@/components/ui/button.jsx'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card.jsx'
import { Badge } from '@/components/ui/badge.jsx'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs.jsx'
import { Progress } from '@/components/ui/progress.jsx'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert.jsx'
import { 
  Activity, 
  TrendingUp, 
  TrendingDown, 
  DollarSign, 
  BarChart3, 
  Settings, 
  AlertTriangle,
  Play,
  Pause,
  RefreshCw,
  Zap,
  Brain,
  Shield,
  Database,
  Wifi,
  WifiOff,
  Bell,
  X
} from 'lucide-react'
import { AppProvider, useApp } from './contexts/AppContext.jsx'
import './App.css'

// Componente de Status da Conexão WebSocket
function ConnectionStatus() {
  const { wsConnected, wsError } = useApp()
  
  return (
    <div className="flex items-center gap-2">
      {wsConnected ? (
        <>
          <Wifi className="h-4 w-4 text-green-400" />
          <span className="text-sm text-green-400">Conectado</span>
        </>
      ) : (
        <>
          <WifiOff className="h-4 w-4 text-red-400" />
          <span className="text-sm text-red-400">
            {wsError ? 'Erro de Conexão' : 'Desconectado'}
          </span>
        </>
      )}
    </div>
  )
}

// Componente de Notificações
function NotificationPanel() {
  const { state, actions } = useApp()
  const { notifications, alerts } = state
  
  const [showNotifications, setShowNotifications] = useState(false)
  
  const unreadCount = notifications.filter(n => !n.read).length + alerts.length
  
  return (
    <div className="relative">
      <Button
        variant="outline"
        size="sm"
        onClick={() => setShowNotifications(!showNotifications)}
        className="text-white border-white/20 hover:bg-white/10 relative"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <Badge className="absolute -top-2 -right-2 h-5 w-5 p-0 text-xs bg-red-500">
            {unreadCount}
          </Badge>
        )}
      </Button>
      
      {showNotifications && (
        <div className="absolute right-0 top-12 w-80 bg-slate-800 border border-white/20 rounded-lg shadow-lg z-50 max-h-96 overflow-y-auto">
          <div className="p-4 border-b border-white/20">
            <h3 className="text-white font-medium">Notificações</h3>
          </div>
          
          <div className="p-2">
            {/* Alertas */}
            {alerts.map((alert) => (
              <div key={alert.id} className="p-3 mb-2 bg-red-500/10 border border-red-500/20 rounded-lg">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="text-red-400 font-medium text-sm">{alert.title}</div>
                    <div className="text-slate-300 text-xs mt-1">{alert.message}</div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => actions.removeAlert(alert.id)}
                    className="h-6 w-6 p-0 text-red-400 hover:bg-red-500/20"
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            ))}
            
            {/* Notificações */}
            {notifications.slice(0, 10).map((notification) => (
              <div key={notification.id} className="p-3 mb-2 bg-white/5 rounded-lg">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="text-white font-medium text-sm">{notification.title}</div>
                    <div className="text-slate-300 text-xs mt-1">{notification.message}</div>
                    <div className="text-slate-400 text-xs mt-1">
                      {new Date(notification.timestamp).toLocaleTimeString()}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => actions.removeNotification(notification.id)}
                    className="h-6 w-6 p-0 text-slate-400 hover:bg-white/10"
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            ))}
            
            {notifications.length === 0 && alerts.length === 0 && (
              <div className="text-center text-slate-400 py-4">
                Nenhuma notificação
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Dashboard() {
  const { state, actions, wsConnected } = useApp()
  const { systemStatus, performance, positions, recentTrades, marketData } = state
  
  const [isRefreshing, setIsRefreshing] = useState(false)

  const refreshData = async () => {
    setIsRefreshing(true)
    
    try {
      // Simular chamada de API para dados não em tempo real
      // Em produção, isso faria chamadas para endpoints REST
      await new Promise(resolve => setTimeout(resolve, 1000))
      
      // Dados mockados para demonstração
      actions.updatePerformance({
        totalPnL: 1247.83 + (Math.random() - 0.5) * 100,
        dailyPnL: 89.45 + (Math.random() - 0.5) * 50,
        winRate: 68.5 + (Math.random() - 0.5) * 10,
        totalTrades: 156 + Math.floor(Math.random() * 5),
        sharpeRatio: 1.34 + (Math.random() - 0.5) * 0.2,
        maxDrawdown: -5.2 + (Math.random() - 0.5) * 2
      })
      
    } catch (error) {
      actions.setError('Erro ao atualizar dados')
    } finally {
      setIsRefreshing(false)
    }
  }

  const toggleSystem = () => {
    const newStatus = !systemStatus.isRunning
    
    actions.updateSystemStatus({
      isRunning: newStatus,
      modules: {
        ai: { status: newStatus ? 'active' : 'inactive', confidence: newStatus ? 87 : 0 },
        risk: { status: newStatus ? 'active' : 'inactive', level: newStatus ? 'low' : 'unknown' },
        data: { status: newStatus ? 'active' : 'inactive', sources: newStatus ? 3 : 0 },
        trading: { status: newStatus ? 'active' : 'inactive', positions: positions.length }
      }
    })
    
    // Enviar comando via WebSocket se conectado
    if (wsConnected) {
      actions.wsSendMessage('system_command', {
        action: newStatus ? 'start' : 'stop',
        timestamp: new Date().toISOString()
      })
    }
    
    // Adicionar notificação
    actions.addNotification({
      type: 'system',
      title: 'Sistema ' + (newStatus ? 'Iniciado' : 'Pausado'),
      message: `RoboTrader foi ${newStatus ? 'iniciado' : 'pausado'} com sucesso`,
      level: 'info'
    })
  }

  // Simular dados em tempo real quando WebSocket não está conectado
  useEffect(() => {
    if (!wsConnected) {
      const interval = setInterval(() => {
        // Simular dados de mercado
        actions.updateMarketData('BTC/USDT', {
          price: 43000 + (Math.random() - 0.5) * 1000,
          volume: Math.random() * 1000000,
          change: (Math.random() - 0.5) * 10
        })
        
        actions.updateMarketData('ETH/USDT', {
          price: 2600 + (Math.random() - 0.5) * 200,
          volume: Math.random() * 500000,
          change: (Math.random() - 0.5) * 8
        })
      }, 5000)
      
      return () => clearInterval(interval)
    }
  }, [wsConnected, actions])

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
      <div className="container mx-auto p-6">
        {/* Header */}
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-4xl font-bold text-white mb-2">RoboTrader 2.0</h1>
            <p className="text-slate-300">Sistema de Trading Automatizado com IA</p>
            <div className="mt-2">
              <ConnectionStatus />
            </div>
          </div>
          <div className="flex gap-4 items-center">
            <NotificationPanel />
            <Button 
              onClick={refreshData} 
              variant="outline" 
              size="sm"
              disabled={isRefreshing}
              className="text-white border-white/20 hover:bg-white/10"
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
              Atualizar
            </Button>
            <Button 
              onClick={toggleSystem}
              variant={systemStatus.isRunning ? "destructive" : "default"}
              size="sm"
            >
              {systemStatus.isRunning ? (
                <>
                  <Pause className="h-4 w-4 mr-2" />
                  Pausar
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-2" />
                  Iniciar
                </>
              )}
            </Button>
          </div>
        </div>

        {/* Status Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Status do Sistema</CardTitle>
              <Activity className="h-4 w-4 text-green-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                <Badge variant={systemStatus.isRunning ? "default" : "destructive"}>
                  {systemStatus.isRunning ? "ATIVO" : "PARADO"}
                </Badge>
              </div>
              <p className="text-xs text-slate-300 mt-1">
                Uptime: {systemStatus.uptime}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">P&L Total</CardTitle>
              <DollarSign className="h-4 w-4 text-green-400" />
            </CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold ${performance.totalPnL >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ${performance.totalPnL.toFixed(2)}
              </div>
              <p className="text-xs text-slate-300 mt-1">
                Hoje: ${performance.dailyPnL.toFixed(2)}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Taxa de Acerto</CardTitle>
              <TrendingUp className="h-4 w-4 text-blue-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-blue-400">
                {performance.winRate.toFixed(1)}%
              </div>
              <p className="text-xs text-slate-300 mt-1">
                {performance.totalTrades} trades
              </p>
            </CardContent>
          </Card>

          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Sharpe Ratio</CardTitle>
              <BarChart3 className="h-4 w-4 text-purple-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-purple-400">
                {performance.sharpeRatio.toFixed(2)}
              </div>
              <p className="text-xs text-slate-300 mt-1">
                Max DD: {performance.maxDrawdown.toFixed(1)}%
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Módulos do Sistema */}
          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="h-5 w-5" />
                Módulos do Sistema
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Brain className="h-4 w-4 text-blue-400" />
                  <span>IA & Machine Learning</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={systemStatus.modules.ai.status === 'active' ? "default" : "secondary"} className="text-xs">
                    {systemStatus.modules.ai.status.toUpperCase()}
                  </Badge>
                  <span className="text-sm text-blue-400">{systemStatus.modules.ai.confidence}%</span>
                </div>
              </div>
              
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Shield className="h-4 w-4 text-green-400" />
                  <span>Gestão de Risco</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={systemStatus.modules.risk.status === 'active' ? "default" : "secondary"} className="text-xs">
                    {systemStatus.modules.risk.status.toUpperCase()}
                  </Badge>
                  <span className="text-sm text-green-400 uppercase">{systemStatus.modules.risk.level}</span>
                </div>
              </div>
              
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-yellow-400" />
                  <span>Coleta de Dados</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={systemStatus.modules.data.status === 'active' ? "default" : "secondary"} className="text-xs">
                    {systemStatus.modules.data.status.toUpperCase()}
                  </Badge>
                  <span className="text-sm text-yellow-400">{systemStatus.modules.data.sources} fontes</span>
                </div>
              </div>
              
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-purple-400" />
                  <span>Execução de Trades</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={systemStatus.modules.trading.status === 'active' ? "default" : "secondary"} className="text-xs">
                    {systemStatus.modules.trading.status.toUpperCase()}
                  </Badge>
                  <span className="text-sm text-purple-400">{positions.length} posições</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Posições Ativas */}
          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader>
              <CardTitle>Posições Ativas</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {positions.length > 0 ? positions.map((position, index) => (
                  <div key={index} className="flex items-center justify-between p-3 bg-white/5 rounded-lg">
                    <div>
                      <div className="font-medium">{position.symbol}</div>
                      <div className="text-sm text-slate-300">
                        {position.side?.toUpperCase()} {position.size}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`font-medium ${position.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        ${position.pnl?.toFixed(2)}
                      </div>
                      <div className="text-sm text-slate-300">
                        {position.confidence}% conf.
                      </div>
                    </div>
                  </div>
                )) : (
                  <div className="text-center text-slate-400 py-4">
                    Nenhuma posição ativa
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Trades Recentes */}
          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader>
              <CardTitle>Trades Recentes</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {recentTrades.length > 0 ? recentTrades.slice(0, 10).map((trade, index) => (
                  <div key={index} className="flex items-center justify-between text-sm">
                    <div>
                      <div className="font-medium">
                        {trade.timestamp ? new Date(trade.timestamp).toLocaleTimeString() : trade.time}
                      </div>
                      <div className="text-slate-300">{trade.symbol}</div>
                    </div>
                    <div className="text-center">
                      <Badge variant={trade.side === 'buy' ? 'default' : 'secondary'} className="text-xs">
                        {trade.side?.toUpperCase()}
                      </Badge>
                      <div className="text-slate-300">${trade.price}</div>
                    </div>
                    <div className="text-right">
                      <div className={`font-medium ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        ${trade.pnl?.toFixed(2)}
                      </div>
                    </div>
                  </div>
                )) : (
                  <div className="text-center text-slate-400 py-4">
                    Nenhum trade recente
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Market Data */}
        {Object.keys(marketData).length > 0 && (
          <div className="mt-6">
            <Card className="bg-white/10 border-white/20 text-white">
              <CardHeader>
                <CardTitle>Dados de Mercado em Tempo Real</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {Object.entries(marketData).map(([symbol, data]) => (
                    <div key={symbol} className="p-4 bg-white/5 rounded-lg">
                      <div className="font-medium text-lg">{symbol}</div>
                      <div className="text-2xl font-bold text-blue-400">
                        ${data.price?.toFixed(2)}
                      </div>
                      <div className={`text-sm ${data.change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {data.change >= 0 ? '+' : ''}{data.change?.toFixed(2)}%
                      </div>
                      <div className="text-xs text-slate-400 mt-1">
                        Vol: {data.volume?.toLocaleString()}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Alert */}
        {!systemStatus.isRunning && (
          <Alert className="mt-6 bg-yellow-500/10 border-yellow-500/20 text-yellow-300">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Sistema Pausado</AlertTitle>
            <AlertDescription>
              O RoboTrader está pausado. Clique em "Iniciar" para retomar as operações.
            </AlertDescription>
          </Alert>
        )}
        
        {!wsConnected && (
          <Alert className="mt-6 bg-orange-500/10 border-orange-500/20 text-orange-300">
            <WifiOff className="h-4 w-4" />
            <AlertTitle>Conexão WebSocket Perdida</AlertTitle>
            <AlertDescription>
              A conexão em tempo real foi perdida. Os dados podem não estar atualizados.
            </AlertDescription>
          </Alert>
        )}
      </div>
    </div>
  )
}

function App() {
  return (
    <AppProvider>
      <Router>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </AppProvider>
  )
}

export default App

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
      <div className="container mx-auto p-6">
        {/* Header */}
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-4xl font-bold text-white mb-2">RoboTrader</h1>
            <p className="text-slate-300">Sistema de Trading Automatizado com IA</p>
          </div>
          <div className="flex gap-4">
            <Button 
              onClick={refreshData} 
              variant="outline" 
              size="sm"
              disabled={isRefreshing}
              className="text-white border-white/20 hover:bg-white/10"
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
              Atualizar
            </Button>
            <Button 
              onClick={toggleSystem}
              variant={data.systemStatus.isRunning ? "destructive" : "default"}
              size="sm"
            >
              {data.systemStatus.isRunning ? (
                <>
                  <Pause className="h-4 w-4 mr-2" />
                  Pausar
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-2" />
                  Iniciar
                </>
              )}
            </Button>
          </div>
        </div>

        {/* Status Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Status do Sistema</CardTitle>
              <Activity className="h-4 w-4 text-green-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                <Badge variant={data.systemStatus.isRunning ? "default" : "destructive"}>
                  {data.systemStatus.isRunning ? "ATIVO" : "PARADO"}
                </Badge>
              </div>
              <p className="text-xs text-slate-300 mt-1">
                Uptime: {data.systemStatus.uptime}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">P&L Total</CardTitle>
              <DollarSign className="h-4 w-4 text-green-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-green-400">
                ${data.performance.totalPnL.toFixed(2)}
              </div>
              <p className="text-xs text-slate-300 mt-1">
                Hoje: ${data.performance.dailyPnL.toFixed(2)}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Taxa de Acerto</CardTitle>
              <TrendingUp className="h-4 w-4 text-blue-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-blue-400">
                {data.performance.winRate}%
              </div>
              <p className="text-xs text-slate-300 mt-1">
                {data.performance.totalTrades} trades
              </p>
            </CardContent>
          </Card>

          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Sharpe Ratio</CardTitle>
              <BarChart3 className="h-4 w-4 text-purple-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-purple-400">
                {data.performance.sharpeRatio}
              </div>
              <p className="text-xs text-slate-300 mt-1">
                Max DD: {data.performance.maxDrawdown}%
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Módulos do Sistema */}
          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="h-5 w-5" />
                Módulos do Sistema
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Brain className="h-4 w-4 text-blue-400" />
                  <span>IA & Machine Learning</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="default" className="text-xs">ATIVO</Badge>
                  <span className="text-sm text-blue-400">{data.systemStatus.modules.ai.confidence}%</span>
                </div>
              </div>
              
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Shield className="h-4 w-4 text-green-400" />
                  <span>Gestão de Risco</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="default" className="text-xs">ATIVO</Badge>
                  <span className="text-sm text-green-400 uppercase">{data.systemStatus.modules.risk.level}</span>
                </div>
              </div>
              
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-yellow-400" />
                  <span>Coleta de Dados</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="default" className="text-xs">ATIVO</Badge>
                  <span className="text-sm text-yellow-400">{data.systemStatus.modules.data.sources} fontes</span>
                </div>
              </div>
              
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-purple-400" />
                  <span>Execução de Trades</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="default" className="text-xs">ATIVO</Badge>
                  <span className="text-sm text-purple-400">{data.systemStatus.modules.trading.positions} posições</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Posições Ativas */}
          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader>
              <CardTitle>Posições Ativas</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {data.positions.map((position, index) => (
                  <div key={index} className="flex items-center justify-between p-3 bg-white/5 rounded-lg">
                    <div>
                      <div className="font-medium">{position.symbol}</div>
                      <div className="text-sm text-slate-300">
                        {position.side.toUpperCase()} {position.size}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`font-medium ${position.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        ${position.pnl.toFixed(2)}
                      </div>
                      <div className="text-sm text-slate-300">
                        {position.confidence}% conf.
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Trades Recentes */}
          <Card className="bg-white/10 border-white/20 text-white">
            <CardHeader>
              <CardTitle>Trades Recentes</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {data.recentTrades.map((trade, index) => (
                  <div key={index} className="flex items-center justify-between text-sm">
                    <div>
                      <div className="font-medium">{trade.time}</div>
                      <div className="text-slate-300">{trade.symbol}</div>
                    </div>
                    <div className="text-center">
                      <Badge variant={trade.side === 'buy' ? 'default' : 'secondary'} className="text-xs">
                        {trade.side.toUpperCase()}
                      </Badge>
                      <div className="text-slate-300">${trade.price}</div>
                    </div>
                    <div className="text-right">
                      <div className={`font-medium ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        ${trade.pnl.toFixed(2)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Alert */}
        {!data.systemStatus.isRunning && (
          <Alert className="mt-6 bg-yellow-500/10 border-yellow-500/20 text-yellow-300">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Sistema Pausado</AlertTitle>
            <AlertDescription>
              O RoboTrader está pausado. Clique em "Iniciar" para retomar as operações.
            </AlertDescription>
          </Alert>
        )}
      </div>
    </div>
  )
}

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  )
}

export default App

