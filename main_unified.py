
    async def _initialize_ai_model(self):
        """Inicializa e treina o modelo de IA ou carrega um existente"""
        logger.info("🧠 Inicializando modelo de IA...")
        
        # Inicializar o modelo de IA (ele tentará carregar um salvo internamente)
        self.ai_model = AdvancedAIModel(input_shape=(config.ai.sequence_length, len(config.data.features)))

        if self.ai_model.is_trained:
            logger.info(f"📥 Modelo salvo carregado (treinado em: {self.ai_model.metrics.get("last_updated", "N/A")})")
            return

        if self.market_data_history.empty:
            logger.warning("⚠️ Sem dados para treinar o modelo de IA")
            return
        
        try:
            # Preparar dados para treinamento
            X, y = self.ai_model.prepare_data(self.market_data_history)
            
            if X.size == 0:
                logger.warning("⚠️ Dados insuficientes após engenharia de features")
                return
            
            if len(X) < 100:  # Mínimo para treinamento robusto
                logger.warning("⚠️ Dados insuficientes para treinamento robusto")
                return
            
            # Dividir em treino e validação
            split_idx = int(len(X) * (1 - config.ai.validation_split))
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train = {k: v[:split_idx] for k, v in y.items()}
            y_val = {k: v[split_idx:] for k, v in y.items()}
            
            # Treinar modelo
            logger.info("🎯 Iniciando treinamento do modelo...")
            history = self.ai_model.train(X_train, y_train, X_val, y_val)
            
            # O modelo já é salvo internamente pelo método train() do ai_model_fixed.py
            logger.info("✅ Modelo de IA treinado e salvo com sucesso")
            
        except Exception as e:
            logger.error(f"❌ Erro no treinamento do modelo: {e}")

    async def _test_news_connectivity(self):
        """Testa conectividade com APIs de notícias"""
        try:
            test_news = self.news_analyzer.get_market_news(["BTC"], hours_back=1)
            if test_news:
                logger.info(f"📰 Conectividade de notícias OK ({len(test_news)} artigos)")
            else:
                logger.warning("⚠️ Nenhuma notícia obtida - verificar APIs")
        except Exception as e:
            logger.warning(f"⚠️ Erro na conectividade de notícias: {e}")
    
    async def run(self):
        """Loop principal do RoboTrader"""
        if not await self.initialize():
            logger.error("❌ Falha na inicialização. Abortando...")
            return
        
        self.is_running = True
        logger.info("🚀 RoboTrader Unificado iniciado - Loop principal ativo")
        
        iteration_count = 0
        last_metrics_update = datetime.now()
        
        try:
            while self.is_running and not self.shutdown_requested:
                iteration_count += 1
                start_time = time.time()
                
                logger.info(f"\n{'='*60}")
                logger.info(f"🔄 Iteração {iteration_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{'='*60}")
                
                # Processar cada símbolo
                for symbol in self.symbols:
                    try:
                        await self._analyze_and_trade(symbol)
                    except Exception as e:
                        logger.error(f"❌ Erro ao processar {symbol}: {e}")
                
                # Atualizar métricas a cada 10 iterações
                if iteration_count % 10 == 0:
                    await self._update_performance_metrics()
                    last_metrics_update = datetime.now()
                
                # Calcular tempo de execução
                execution_time = time.time() - start_time
                logger.info(f"⏱️ Iteração concluída em {execution_time:.2f}s")
                
                # Aguardar próxima iteração
                sleep_time = max(0, config.api.data_fetch_interval_seconds - execution_time)
                if sleep_time > 0:
                    logger.info(f"😴 Aguardando {sleep_time:.1f}s para próxima iteração...")
                    await asyncio.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.info("⏹️ Interrupção manual detectada")
        except Exception as e:
            logger.error(f"❌ Erro crítico no loop principal: {e}")
        finally:
            await self._shutdown()
    
    async def _analyze_and_trade(self, symbol: str):
        """Analisa mercado e executa trades para um símbolo"""
        logger.info(f"🔍 Analisando {symbol}...")
        
        try:
            # 1. Atualizar dados de mercado
            await self._update_market_data(symbol)
            
            if len(self.market_data_history) < config.ai.sequence_length + 50:
                logger.warning(f"⚠️ Dados insuficientes para {symbol}")
                return
            
            # 2. Preparar dados para análise
            current_data = self.market_data_history.tail(config.ai.sequence_length + 100).copy()
            
            # 3. Análise de IA
            ai_signal = await self._get_ai_signal(current_data)
            
            # 4. Análise Quântica
            quantum_signal = await self._get_quantum_signal(current_data)
            
            # 5. Análise de Notícias
            news_sentiment = await self._get_news_sentiment(symbol)
            
            # 6. Avaliação de Risco
            risk_assessment = await self._assess_risk(
                symbol, ai_signal, quantum_signal, news_sentiment, current_data
            )
            
            # 7. Decisão Final e Execução
            await self._make_trading_decision(
                symbol, ai_signal, quantum_signal, news_sentiment, risk_assessment
            )
            
        except Exception as e:
            logger.error(f"❌ Erro na análise de {symbol}: {e}")
    
    async def _update_market_data(self, symbol: str):
        """Atualiza dados de mercado para um símbolo"""
        try:
            new_data = await self.broker.get_market_data_async(symbol, self.timeframe, 5)
            
            if not new_data.empty:
                # Salvar no banco
                db_manager.save_market_data(symbol, self.timeframe, new_data)
                
                # Atualizar histórico em memória
                self.market_data_history = pd.concat([self.market_data_history, new_data], ignore_index=True)
                
                # Manter apenas dados necessários em memória
                max_rows = config.ai.sequence_length + 200
                if len(self.market_data_history) > max_rows:
                    self.market_data_history = self.market_data_history.tail(max_rows).reset_index(drop=True)
                
                logger.debug(f"📊 Dados atualizados para {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Erro ao atualizar dados de {symbol}: {e}")
    
    async def _get_ai_signal(self, data: pd.DataFrame) -> Dict:
        """Obtém sinal do modelo de IA"""
        try:
            if not self.ai_model or not self.ai_model.is_trained:
                return {'action': 'hold', 'confidence': 0.0, 'reason': 'Modelo não treinado'}
            
            X, _ = self.ai_model.prepare_data(data)
            if X.size == 0:
                return {'action': 'hold', 'confidence': 0.0, 'reason': 'Dados insuficientes'}
            
            predictions = self.ai_model.predict(X[-1:])
            signal = self.ai_model.generate_advanced_signal(predictions)
            
            logger.info(f"🧠 IA: {signal['action'].upper()} (Confiança: {signal['confidence']:.2f})")
            return signal
            
        except Exception as e:
            logger.error(f"❌ Erro no sinal de IA: {e}")
            return {'action': 'hold', 'confidence': 0.0, 'reason': f'Erro: {e}'}
    
    async def _get_quantum_signal(self, data: pd.DataFrame) -> Dict:
        """Obtém sinal do analisador quântico"""
        try:
            if data.empty:
                return {'action': 'hold', 'confidence': 0.0, 'reason': 'Dados insuficientes'}
            
            # Re-encode data for quantum analyzer if needed (e.g., new market regime)
            self.quantum_analyzer.encode_market_data(data.tail(100))
            
            quantum_signal = self.quantum_analyzer.analyze_market_regime(data)
            
            logger.info(f"⚛️ Quântico: {quantum_signal['regime'].upper()} (Score: {quantum_signal['score']:.2f})")
            return quantum_signal
            
        except Exception as e:
            logger.error(f"❌ Erro no sinal quântico: {e}")
            return {'action': 'hold', 'confidence': 0.0, 'reason': f'Erro: {e}'}
    
    async def _get_news_sentiment(self, symbol: str) -> Dict:
        """Obtém sentimento de notícias"""
        try:
            news_articles = self.news_analyzer.get_market_news([symbol], hours_back=2)
            sentiment = self.news_analyzer.analyze_sentiment(news_articles)
            
            logger.info(f"📰 Notícias: Sentimento {sentiment['overall_sentiment'].upper()} (Score: {sentiment['sentiment_score']:.2f})")
            return sentiment
            
        except Exception as e:
            logger.error(f"❌ Erro no sentimento de notícias: {e}")
            return {'overall_sentiment': 'neutral', 'sentiment_score': 0.0, 'reason': f'Erro: {e}'}
    
    async def _assess_risk(self, symbol: str, ai_signal: Dict, quantum_signal: Dict, 
                          news_sentiment: Dict, current_data: pd.DataFrame) -> Dict:
        """Avalia o risco da operação"""
        try:
            risk_assessment = self.risk_manager.assess_risk(
                symbol,
                ai_signal,
                quantum_signal,
                news_sentiment,
                current_data
            )
            
            logger.info(f"🚨 Risco: {risk_assessment['risk_level'].upper()} (Score: {risk_assessment['risk_score']:.2f})")
            return risk_assessment
            
        except Exception as e:
            logger.error(f"❌ Erro na avaliação de risco: {e}")
            return {'risk_level': 'high', 'risk_score': 1.0, 'reason': f'Erro: {e}'}
    
    async def _make_trading_decision(self, symbol: str, ai_signal: Dict, quantum_signal: Dict,
                                    news_sentiment: Dict, risk_assessment: Dict):
        """Toma a decisão final de trading e executa a ordem"""
        logger.info(f"⚖️ Tomando decisão para {symbol}...")
        
        try:
            # Verificar saldo antes de qualquer decisão de trade
            account_balance = await self.broker.get_account_balance()
            if account_balance < config.trading.min_balance_for_trade:
                logger.warning(f"⚠️ Saldo insuficiente para operar. Saldo atual: {account_balance:.2f}")
                return

            # Lógica de decisão combinada
            action = ai_signal["action"]
            confidence = ai_signal["confidence"]
            
            # Ajustar decisão com base em outros sinais e risco
            if risk_assessment["risk_level"] == "high" and action != "hold":
                logger.warning("🚨 Risco alto detectado, anulando trade.")
                action = "hold"
                confidence = 0.0
            
            if quantum_signal["regime"] == "volatile" and action != "hold":
                logger.warning("⚛️ Regime volátil detectado, reduzindo confiança.")
                confidence *= 0.7
            
            if news_sentiment["overall_sentiment"] == "negative" and action == "buy":
                logger.warning("📰 Notícias negativas, anulando compra.")
                action = "hold"
                confidence = 0.0
            
            # Circuit Breaker: Limite de perdas consecutivas
            if self.risk_manager.consecutive_losses >= config.trading.consecutive_losses_limit:
                logger.critical("⛔ Circuit Breaker ativado: Limite de perdas consecutivas atingido. Parando trades.")
                self.shutdown_requested = True # Solicita o desligamento do robô
                return

            if action != "hold" and confidence >= config.trading.min_confidence / 100.0:
                # Calcular tamanho da ordem
                available_balance = account_balance * config.trading.max_position_size
                order_amount = available_balance / self.market_data_history['close'].iloc[-1]
                
                # Executar ordem
                trade_id = await self.order_executor.execute_order(
                    symbol=symbol,
                    side=action,
                    amount=order_amount,
                    price=self.market_data_history['close'].iloc[-1] # Preço atual
                )
                
                if trade_id:
                    logger.info(f"✅ Ordem {action.upper()} executada para {symbol}. ID: {trade_id}")
                    # Salvar trade no banco
                    trade_record = TradeRecord(
                        timestamp=datetime.now(),
                        symbol=symbol,
                        side=action,
                        amount=order_amount,
                        price=self.market_data_history['close'].iloc[-1],
                        total_value=order_amount * self.market_data_history['close'].iloc[-1],
                        fees=0.0, # Calcular fees reais da corretora
                        pnl=0.0, # PnL inicial
                        strategy="combined_ai_quantum_news",
                        confidence=confidence,
                        ai_signal=ai_signal['action'],
                        quantum_signal=quantum_signal['regime'],
                        news_sentiment=news_sentiment['overall_sentiment'],
                        risk_score=risk_assessment['risk_score'],
                        status="executed"
                    )
                    db_manager.save_trade(trade_record)
                else:
                    logger.error(f"❌ Falha ao executar ordem {action.upper()} para {symbol}")
            else:
                logger.info(f"🚫 Decisão: HOLD para {symbol} (Confiança: {confidence:.2f}, Risco: {risk_assessment['risk_level']})")
                
        except Exception as e:
            logger.error(f"❌ Erro na decisão de trading: {e}")
    
    async def _update_performance_metrics(self):
        """Atualiza e salva métricas de performance"""
        logger.info("📈 Atualizando métricas de performance...")
        try:
            # Obter trades recentes do banco
            recent_trades = db_manager.get_trades(limit=100)
            
            if recent_trades:
                df_trades = pd.DataFrame([t.to_dict() for t in recent_trades])
                
                # Calcular PnL (simplificado, em produção seria mais complexo)
                # Assumindo que o PnL é calculado externamente ou na corretora
                total_pnl = df_trades['pnl'].sum()
                win_rate = (df_trades['pnl'] > 0).sum() / len(df_trades) * 100
                
                self.performance_metrics['total_pnl'] = total_pnl
                self.performance_metrics['win_rate'] = win_rate
                self.performance_metrics['last_update'] = datetime.now()
                
                # Salvar métricas no banco
                db_manager.save_performance_metrics(self.performance_metrics)
                logger.info(f"✅ Métricas atualizadas: PnL Total: {total_pnl:.2f}, Win Rate: {win_rate:.2f}%")
            else:
                logger.warning("⚠️ Sem trades para calcular métricas")
                
        except Exception as e:
            logger.error(f"❌ Erro ao atualizar métricas de performance: {e}")
    
    async def _shutdown(self):
        """Executa shutdown graceful do sistema"""
        logger.info("👋 Iniciando shutdown do RoboTrader Unificado...")
        self.is_running = False
        
        if self.model_retraining_system:
            self.model_retraining_system.stop_scheduler()
            logger.info("Scheduler de retreinamento parado.")

        # Salvar estado final
        # db_manager.save_system_state(self.get_system_state())
        
        logger.info("✅ RoboTrader Unificado desligado.")

# Função principal para execução
async def main():
    trader = RoboTraderUnified()
    await trader.run()

if __name__ == "__main__":
    asyncio.run(main())




