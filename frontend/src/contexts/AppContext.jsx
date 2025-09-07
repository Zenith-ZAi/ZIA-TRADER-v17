/**
 * Contexto da Aplicação - Gerencia estado global e WebSocket
 */

import React, { createContext, useContext, useReducer, useEffect } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'

// Estado inicial
const initialState = {
  // Autenticação
  user: null,
  token: localStorage.getItem('access_token'),
  isAuthenticated: false,
  
  // Sistema
  systemStatus: {
    isRunning: false,
    uptime: '0m',
    lastUpdate: null,
    modules: {
      ai: { status: 'inactive', confidence: 0 },
      risk: { status: 'inactive', level: 'unknown' },
      data: { status: 'inactive', sources: 0 },
      trading: { status: 'inactive', positions: 0 }
    }
  },
  
  // Performance
  performance: {
    totalPnL: 0,
    dailyPnL: 0,
    winRate: 0,
    totalTrades: 0,
    sharpeRatio: 0,
    maxDrawdown: 0
  },
  
  // Trading
  positions: [],
  recentTrades: [],
  marketData: {},
  
  // Notificações
  notifications: [],
  alerts: [],
  
  // UI
  isLoading: false,
  error: null,
  
  // WebSocket
  wsConnected: false,
  wsError: null
}

// Actions
const actionTypes = {
  // Auth
  SET_USER: 'SET_USER',
  SET_TOKEN: 'SET_TOKEN',
  LOGOUT: 'LOGOUT',
  
  // System
  UPDATE_SYSTEM_STATUS: 'UPDATE_SYSTEM_STATUS',
  UPDATE_PERFORMANCE: 'UPDATE_PERFORMANCE',
  
  // Trading
  UPDATE_POSITIONS: 'UPDATE_POSITIONS',
  ADD_TRADE: 'ADD_TRADE',
  UPDATE_MARKET_DATA: 'UPDATE_MARKET_DATA',
  
  // Notifications
  ADD_NOTIFICATION: 'ADD_NOTIFICATION',
  REMOVE_NOTIFICATION: 'REMOVE_NOTIFICATION',
  ADD_ALERT: 'ADD_ALERT',
  REMOVE_ALERT: 'REMOVE_ALERT',
  
  // UI
  SET_LOADING: 'SET_LOADING',
  SET_ERROR: 'SET_ERROR',
  CLEAR_ERROR: 'CLEAR_ERROR',
  
  // WebSocket
  SET_WS_CONNECTED: 'SET_WS_CONNECTED',
  SET_WS_ERROR: 'SET_WS_ERROR'
}

// Reducer
const appReducer = (state, action) => {
  switch (action.type) {
    case actionTypes.SET_USER:
      return {
        ...state,
        user: action.payload,
        isAuthenticated: !!action.payload
      }
    
    case actionTypes.SET_TOKEN:
      if (action.payload) {
        localStorage.setItem('access_token', action.payload)
      } else {
        localStorage.removeItem('access_token')
      }
      return {
        ...state,
        token: action.payload,
        isAuthenticated: !!action.payload
      }
    
    case actionTypes.LOGOUT:
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      return {
        ...initialState,
        token: null,
        isAuthenticated: false
      }
    
    case actionTypes.UPDATE_SYSTEM_STATUS:
      return {
        ...state,
        systemStatus: {
          ...state.systemStatus,
          ...action.payload,
          lastUpdate: new Date().toISOString()
        }
      }
    
    case actionTypes.UPDATE_PERFORMANCE:
      return {
        ...state,
        performance: {
          ...state.performance,
          ...action.payload
        }
      }
    
    case actionTypes.UPDATE_POSITIONS:
      return {
        ...state,
        positions: action.payload
      }
    
    case actionTypes.ADD_TRADE:
      return {
        ...state,
        recentTrades: [action.payload, ...state.recentTrades].slice(0, 50) // Manter apenas os 50 mais recentes
      }
    
    case actionTypes.UPDATE_MARKET_DATA:
      return {
        ...state,
        marketData: {
          ...state.marketData,
          [action.payload.symbol]: {
            ...state.marketData[action.payload.symbol],
            ...action.payload.data,
            timestamp: new Date().toISOString()
          }
        }
      }
    
    case actionTypes.ADD_NOTIFICATION:
      return {
        ...state,
        notifications: [
          {
            id: Date.now(),
            timestamp: new Date().toISOString(),
            ...action.payload
          },
          ...state.notifications
        ].slice(0, 100) // Manter apenas as 100 mais recentes
      }
    
    case actionTypes.REMOVE_NOTIFICATION:
      return {
        ...state,
        notifications: state.notifications.filter(n => n.id !== action.payload)
      }
    
    case actionTypes.ADD_ALERT:
      return {
        ...state,
        alerts: [
          {
            id: Date.now(),
            timestamp: new Date().toISOString(),
            ...action.payload
          },
          ...state.alerts
        ].slice(0, 20) // Manter apenas os 20 mais recentes
      }
    
    case actionTypes.REMOVE_ALERT:
      return {
        ...state,
        alerts: state.alerts.filter(a => a.id !== action.payload)
      }
    
    case actionTypes.SET_LOADING:
      return {
        ...state,
        isLoading: action.payload
      }
    
    case actionTypes.SET_ERROR:
      return {
        ...state,
        error: action.payload,
        isLoading: false
      }
    
    case actionTypes.CLEAR_ERROR:
      return {
        ...state,
        error: null
      }
    
    case actionTypes.SET_WS_CONNECTED:
      return {
        ...state,
        wsConnected: action.payload
      }
    
    case actionTypes.SET_WS_ERROR:
      return {
        ...state,
        wsError: action.payload
      }
    
    default:
      return state
  }
}

// Context
const AppContext = createContext()

// Provider
export const AppProvider = ({ children }) => {
  const [state, dispatch] = useReducer(appReducer, initialState)
  
  // WebSocket hook
  const {
    isConnected: wsConnected,
    connectionError: wsError,
    subscribe,
    unsubscribe,
    onEvent,
    sendMessage
  } = useWebSocket(state.token)
  
  // Atualizar estado do WebSocket
  useEffect(() => {
    dispatch({ type: actionTypes.SET_WS_CONNECTED, payload: wsConnected })
  }, [wsConnected])
  
  useEffect(() => {
    dispatch({ type: actionTypes.SET_WS_ERROR, payload: wsError })
  }, [wsError])
  
  // Configurar event listeners do WebSocket
  useEffect(() => {
    if (!wsConnected) return
    
    // Market data
    const unsubMarketData = onEvent('market_data', (data) => {
      dispatch({
        type: actionTypes.UPDATE_MARKET_DATA,
        payload: { symbol: data.symbol, data }
      })
    })
    
    // Trade signals
    const unsubTradeSignal = onEvent('trade_signal', (data) => {
      dispatch({
        type: actionTypes.ADD_TRADE,
        payload: {
          ...data,
          timestamp: new Date().toISOString()
        }
      })
      
      // Adicionar notificação
      dispatch({
        type: actionTypes.ADD_NOTIFICATION,
        payload: {
          type: 'trade',
          title: 'Novo Trade Executado',
          message: `${data.side?.toUpperCase()} ${data.symbol} - ${data.quantity}`,
          level: 'info'
        }
      })
    })
    
    // Portfolio updates
    const unsubPortfolio = onEvent('portfolio_update', (data) => {
      if (data.positions) {
        dispatch({ type: actionTypes.UPDATE_POSITIONS, payload: data.positions })
      }
      
      if (data.performance) {
        dispatch({ type: actionTypes.UPDATE_PERFORMANCE, payload: data.performance })
      }
    })
    
    // System status
    const unsubSystemStatus = onEvent('system_status', (data) => {
      dispatch({ type: actionTypes.UPDATE_SYSTEM_STATUS, payload: data })
    })
    
    // Alerts
    const unsubAlert = onEvent('alert', (data) => {
      dispatch({
        type: actionTypes.ADD_ALERT,
        payload: {
          level: data.level || 'info',
          title: data.title || 'Alerta',
          message: data.message,
          data: data.data
        }
      })
    })
    
    // Notifications
    const unsubNotification = onEvent('notification', (data) => {
      dispatch({
        type: actionTypes.ADD_NOTIFICATION,
        payload: {
          type: data.type || 'info',
          title: data.title || 'Notificação',
          message: data.message,
          level: data.level || 'info'
        }
      })
    })
    
    // Subscrever aos canais necessários
    subscribe('market_data', { symbols: ['BTC/USDT', 'ETH/USDT'] })
    subscribe('trade_signals')
    subscribe('portfolio_updates')
    subscribe('system_alerts')
    subscribe('notifications')
    
    // Cleanup
    return () => {
      unsubMarketData()
      unsubTradeSignal()
      unsubPortfolio()
      unsubSystemStatus()
      unsubAlert()
      unsubNotification()
    }
  }, [wsConnected, onEvent, subscribe])
  
  // Actions
  const actions = {
    // Auth
    setUser: (user) => dispatch({ type: actionTypes.SET_USER, payload: user }),
    setToken: (token) => dispatch({ type: actionTypes.SET_TOKEN, payload: token }),
    logout: () => dispatch({ type: actionTypes.LOGOUT }),
    
    // System
    updateSystemStatus: (status) => dispatch({ type: actionTypes.UPDATE_SYSTEM_STATUS, payload: status }),
    updatePerformance: (performance) => dispatch({ type: actionTypes.UPDATE_PERFORMANCE, payload: performance }),
    
    // Trading
    updatePositions: (positions) => dispatch({ type: actionTypes.UPDATE_POSITIONS, payload: positions }),
    addTrade: (trade) => dispatch({ type: actionTypes.ADD_TRADE, payload: trade }),
    updateMarketData: (symbol, data) => dispatch({ 
      type: actionTypes.UPDATE_MARKET_DATA, 
      payload: { symbol, data } 
    }),
    
    // Notifications
    addNotification: (notification) => dispatch({ type: actionTypes.ADD_NOTIFICATION, payload: notification }),
    removeNotification: (id) => dispatch({ type: actionTypes.REMOVE_NOTIFICATION, payload: id }),
    addAlert: (alert) => dispatch({ type: actionTypes.ADD_ALERT, payload: alert }),
    removeAlert: (id) => dispatch({ type: actionTypes.REMOVE_ALERT, payload: id }),
    
    // UI
    setLoading: (loading) => dispatch({ type: actionTypes.SET_LOADING, payload: loading }),
    setError: (error) => dispatch({ type: actionTypes.SET_ERROR, payload: error }),
    clearError: () => dispatch({ type: actionTypes.CLEAR_ERROR }),
    
    // WebSocket
    wsSubscribe: subscribe,
    wsUnsubscribe: unsubscribe,
    wsSendMessage: sendMessage
  }
  
  const value = {
    state,
    actions,
    wsConnected,
    wsError
  }
  
  return (
    <AppContext.Provider value={value}>
      {children}
    </AppContext.Provider>
  )
}

// Hook para usar o contexto
export const useApp = () => {
  const context = useContext(AppContext)
  if (!context) {
    throw new Error('useApp deve ser usado dentro de AppProvider')
  }
  return context
}

export default AppContext

