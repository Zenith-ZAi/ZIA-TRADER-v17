/**
 * Hook personalizado para gerenciar conexão WebSocket
 * Integra com o sistema de autenticação e fornece comunicação em tempo real
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { io } from 'socket.io-client'

const WEBSOCKET_URL = process.env.REACT_APP_WEBSOCKET_URL || 'http://localhost:5000'

export const useWebSocket = (token = null) => {
  const [socket, setSocket] = useState(null)
  const [isConnected, setIsConnected] = useState(false)
  const [connectionError, setConnectionError] = useState(null)
  const [lastMessage, setLastMessage] = useState(null)
  const [subscriptions, setSubscriptions] = useState(new Set())
  
  // Refs para evitar re-renders desnecessários
  const reconnectAttempts = useRef(0)
  const maxReconnectAttempts = useRef(5)
  const reconnectTimeout = useRef(null)
  const heartbeatInterval = useRef(null)
  
  // Callbacks para eventos
  const eventCallbacks = useRef(new Map())

  // Conectar ao WebSocket
  const connect = useCallback(() => {
    if (!token) {
      setConnectionError('Token de autenticação necessário')
      return
    }

    try {
      const socketInstance = io(WEBSOCKET_URL, {
        auth: { token },
        query: { token },
        transports: ['websocket', 'polling'],
        timeout: 10000,
        reconnection: false // Gerenciaremos a reconexão manualmente
      })

      // Event listeners
      socketInstance.on('connect', () => {
        console.log('WebSocket conectado:', socketInstance.id)
        setIsConnected(true)
        setConnectionError(null)
        reconnectAttempts.current = 0
        
        // Iniciar heartbeat
        startHeartbeat(socketInstance)
        
        // Re-subscrever aos canais anteriores
        subscriptions.forEach(subscription => {
          socketInstance.emit('subscribe', subscription)
        })
      })

      socketInstance.on('disconnect', (reason) => {
        console.log('WebSocket desconectado:', reason)
        setIsConnected(false)
        stopHeartbeat()
        
        // Tentar reconectar se não foi desconexão intencional
        if (reason !== 'io client disconnect') {
          scheduleReconnect()
        }
      })

      socketInstance.on('connect_error', (error) => {
        console.error('Erro de conexão WebSocket:', error)
        setConnectionError(error.message)
        setIsConnected(false)
        scheduleReconnect()
      })

      // Eventos específicos do sistema
      socketInstance.on('market_data', (data) => {
        setLastMessage({ type: 'market_data', data, timestamp: new Date() })
        triggerCallback('market_data', data)
      })

      socketInstance.on('trade_signal', (data) => {
        setLastMessage({ type: 'trade_signal', data, timestamp: new Date() })
        triggerCallback('trade_signal', data)
      })

      socketInstance.on('portfolio_update', (data) => {
        setLastMessage({ type: 'portfolio_update', data, timestamp: new Date() })
        triggerCallback('portfolio_update', data)
      })

      socketInstance.on('system_status', (data) => {
        setLastMessage({ type: 'system_status', data, timestamp: new Date() })
        triggerCallback('system_status', data)
      })

      socketInstance.on('alert', (data) => {
        setLastMessage({ type: 'alert', data, timestamp: new Date() })
        triggerCallback('alert', data)
      })

      socketInstance.on('notification', (data) => {
        setLastMessage({ type: 'notification', data, timestamp: new Date() })
        triggerCallback('notification', data)
      })

      socketInstance.on('error', (data) => {
        console.error('Erro WebSocket:', data)
        setLastMessage({ type: 'error', data, timestamp: new Date() })
        triggerCallback('error', data)
      })

      socketInstance.on('subscription_confirmed', (data) => {
        console.log('Subscrição confirmada:', data)
        triggerCallback('subscription_confirmed', data)
      })

      socketInstance.on('unsubscription_confirmed', (data) => {
        console.log('Cancelamento de subscrição confirmado:', data)
        triggerCallback('unsubscription_confirmed', data)
      })

      socketInstance.on('heartbeat_response', (data) => {
        // Heartbeat recebido, conexão está ativa
        triggerCallback('heartbeat_response', data)
      })

      setSocket(socketInstance)

    } catch (error) {
      console.error('Erro ao criar conexão WebSocket:', error)
      setConnectionError(error.message)
    }
  }, [token])

  // Desconectar
  const disconnect = useCallback(() => {
    if (socket) {
      socket.disconnect()
      setSocket(null)
      setIsConnected(false)
      stopHeartbeat()
      clearReconnectTimeout()
    }
  }, [socket])

  // Agendar reconexão
  const scheduleReconnect = useCallback(() => {
    if (reconnectAttempts.current >= maxReconnectAttempts.current) {
      setConnectionError('Máximo de tentativas de reconexão atingido')
      return
    }

    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000) // Backoff exponencial
    reconnectAttempts.current++

    console.log(`Tentando reconectar em ${delay}ms (tentativa ${reconnectAttempts.current})`)

    reconnectTimeout.current = setTimeout(() => {
      if (!isConnected) {
        connect()
      }
    }, delay)
  }, [connect, isConnected])

  // Limpar timeout de reconexão
  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeout.current) {
      clearTimeout(reconnectTimeout.current)
      reconnectTimeout.current = null
    }
  }, [])

  // Iniciar heartbeat
  const startHeartbeat = useCallback((socketInstance) => {
    heartbeatInterval.current = setInterval(() => {
      if (socketInstance && socketInstance.connected) {
        socketInstance.emit('heartbeat')
      }
    }, 30000) // Heartbeat a cada 30 segundos
  }, [])

  // Parar heartbeat
  const stopHeartbeat = useCallback(() => {
    if (heartbeatInterval.current) {
      clearInterval(heartbeatInterval.current)
      heartbeatInterval.current = null
    }
  }, [])

  // Subscrever a um canal
  const subscribe = useCallback((subscriptionType, params = {}) => {
    if (!socket || !isConnected) {
      console.warn('WebSocket não conectado, não é possível subscrever')
      return false
    }

    const subscription = { type: subscriptionType, params }
    setSubscriptions(prev => new Set([...prev, subscription]))
    
    socket.emit('subscribe', subscription)
    return true
  }, [socket, isConnected])

  // Cancelar subscrição
  const unsubscribe = useCallback((subscriptionType) => {
    if (!socket || !isConnected) {
      console.warn('WebSocket não conectado, não é possível cancelar subscrição')
      return false
    }

    setSubscriptions(prev => {
      const newSubs = new Set()
      prev.forEach(sub => {
        if (sub.type !== subscriptionType) {
          newSubs.add(sub)
        }
      })
      return newSubs
    })
    
    socket.emit('unsubscribe', { type: subscriptionType })
    return true
  }, [socket, isConnected])

  // Enviar mensagem personalizada
  const sendMessage = useCallback((event, data) => {
    if (!socket || !isConnected) {
      console.warn('WebSocket não conectado, não é possível enviar mensagem')
      return false
    }

    socket.emit(event, data)
    return true
  }, [socket, isConnected])

  // Registrar callback para evento
  const onEvent = useCallback((eventType, callback) => {
    if (!eventCallbacks.current.has(eventType)) {
      eventCallbacks.current.set(eventType, new Set())
    }
    eventCallbacks.current.get(eventType).add(callback)

    // Retornar função para remover o callback
    return () => {
      const callbacks = eventCallbacks.current.get(eventType)
      if (callbacks) {
        callbacks.delete(callback)
        if (callbacks.size === 0) {
          eventCallbacks.current.delete(eventType)
        }
      }
    }
  }, [])

  // Disparar callbacks
  const triggerCallback = useCallback((eventType, data) => {
    const callbacks = eventCallbacks.current.get(eventType)
    if (callbacks) {
      callbacks.forEach(callback => {
        try {
          callback(data)
        } catch (error) {
          console.error(`Erro ao executar callback para ${eventType}:`, error)
        }
      })
    }
  }, [])

  // Obter estatísticas da conexão
  const getConnectionStats = useCallback(() => {
    return {
      isConnected,
      connectionError,
      reconnectAttempts: reconnectAttempts.current,
      subscriptionsCount: subscriptions.size,
      socketId: socket?.id || null,
      lastMessage: lastMessage?.timestamp || null
    }
  }, [isConnected, connectionError, subscriptions.size, socket?.id, lastMessage])

  // Effect para conectar/desconectar
  useEffect(() => {
    if (token) {
      connect()
    }

    return () => {
      disconnect()
      clearReconnectTimeout()
    }
  }, [token, connect, disconnect, clearReconnectTimeout])

  // Cleanup ao desmontar
  useEffect(() => {
    return () => {
      stopHeartbeat()
      clearReconnectTimeout()
      if (socket) {
        socket.disconnect()
      }
    }
  }, [socket, stopHeartbeat, clearReconnectTimeout])

  return {
    // Estado
    isConnected,
    connectionError,
    lastMessage,
    subscriptions: Array.from(subscriptions),
    
    // Métodos
    connect,
    disconnect,
    subscribe,
    unsubscribe,
    sendMessage,
    onEvent,
    getConnectionStats,
    
    // Utilitários
    reconnect: () => {
      disconnect()
      setTimeout(connect, 1000)
    }
  }
}

