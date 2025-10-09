import express from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';

const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';

// Create the MCP server instance with all tools
const createMcpServer = () => {
  const server = new McpServer({
    name: 'deribit-mcp-server',
    version: '2.0.0',
  });

  // ========================================
  // EXISTING TOOLS (UNCHANGED)
  // ========================================

  // Tool 1: Get Ticker Data (ORIGINAL - UNCHANGED)
  server.tool(
    'get_ticker',
    'Get ticker data for a specific instrument including price, volume, and funding rate',
    {
      instrument_name: z.string().describe('The instrument name (e.g., BTC-PERPETUAL, ETH-PERPETUAL)'),
    },
    async ({ instrument_name }) => {
      try {
        const url = `${DERIBIT_API_BASE}/public/ticker?instrument_name=${instrument_name}`;
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
          return {
            content: [{
              type: 'text',
              text: `Error: ${data.error.message}`
            }]
          };
        }

        const ticker = data.result;
        const formatted = `📊 **${instrument_name}** Ticker Data:
        
**Price Information:**
• Last Price: $${ticker.last_price?.toLocaleString() || 'N/A'}
• Mark Price: $${ticker.mark_price?.toLocaleString() || 'N/A'}
• Best Bid: $${ticker.best_bid_price?.toLocaleString() || 'N/A'}
• Best Ask: $${ticker.best_ask_price?.toLocaleString() || 'N/A'}

**Volume & Interest:**
• 24h Volume: ${ticker.stats?.volume || 'N/A'} ${ticker.underlying_index || ''}
• Open Interest: ${ticker.open_interest || 'N/A'}

**Funding (if applicable):**
• Current Rate: ${ticker.current_funding ? (ticker.current_funding * 100).toFixed(4) + '%' : 'N/A'}
• 8h Funding: ${ticker.funding_8h ? (ticker.funding_8h * 100).toFixed(4) + '%' : 'N/A'}

**Statistics:**
• 24h High: $${ticker.stats?.high || 'N/A'}
• 24h Low: $${ticker.stats?.low || 'N/A'}
• State: ${ticker.state || 'N/A'}`;

        return {
          content: [{
            type: 'text',
            text: formatted
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error fetching ticker: ${error.message}`
          }]
        };
      }
    }
  );

  // Tool 2: Get Available Instruments (ORIGINAL - UNCHANGED)
  server.tool(
    'get_instruments',
    'Get all available trading instruments for a specific currency',
    {
      currency: z.string().describe('Currency symbol (BTC, ETH, SOL, etc.)'),
      kind: z.enum(['future', 'option', 'spot', 'future_combo', 'option_combo']).optional().describe('Instrument kind (default: future)'),
      expired: z.boolean().optional().describe('Include expired instruments (default: false)')
    },
    async ({ currency, kind = 'future', expired = false }) => {
      try {
        const url = `${DERIBIT_API_BASE}/public/get_instruments?currency=${currency}&kind=${kind}&expired=${expired}`;
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
          return {
            content: [{
              type: 'text',
              text: `Error: ${data.error.message}`
            }]
          };
        }

        const instruments = data.result;
        const formatted = `📋 **${currency} ${kind.toUpperCase()} Instruments** (${instruments.length} found):

${instruments.slice(0, 20).map(inst => 
  `• **${inst.instrument_name}**
   Type: ${inst.settlement_period || inst.kind}
   ${inst.min_trade_amount ? `Min Trade: ${inst.min_trade_amount}` : ''}
   ${inst.contract_size ? `Contract Size: ${inst.contract_size}` : ''}
   State: ${inst.is_active ? '✅ Active' : '❌ Inactive'}`
).join('\n\n')}

${instruments.length > 20 ? `\n...and ${instruments.length - 20} more instruments` : ''}`;

        return {
          content: [{
            type: 'text',
            text: formatted
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error fetching instruments: ${error.message}`
          }]
        };
      }
    }
  );

  // Tool 3: Get Order Book (ORIGINAL - UNCHANGED)
  server.tool(
    'get_orderbook',
    'Get the order book for a specific instrument',
    {
      instrument_name: z.string().describe('The instrument name (e.g., BTC-PERPETUAL)'),
      depth: z.number().optional().describe('Number of price levels to return (default: 10, max: 10000)')
    },
    async ({ instrument_name, depth = 10 }) => {
      try {
        const url = `${DERIBIT_API_BASE}/public/get_order_book?instrument_name=${instrument_name}&depth=${depth}`;
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
          return {
            content: [{
              type: 'text',
              text: `Error: ${data.error.message}`
            }]
          };
        }

        const book = data.result;
        const bids = book.bids.slice(0, 10);
        const asks = book.asks.slice(0, 10);

        const formatted = `📖 **${instrument_name}** Order Book:

**Asks (Selling):**
${asks.reverse().map(([price, amount]) => 
  `$${price.toLocaleString()} | ${amount.toFixed(4)}`
).join('\n')}

**━━━━━━━━━━━━━━━━━━━━━━━━━**
**Last Price: $${book.last_price?.toLocaleString() || 'N/A'}**
**Spread: $${(asks[0]?.[0] - bids[0]?.[0])?.toFixed(2) || 'N/A'}**
**━━━━━━━━━━━━━━━━━━━━━━━━━**

**Bids (Buying):**
${bids.map(([price, amount]) => 
  `$${price.toLocaleString()} | ${amount.toFixed(4)}`
).join('\n')}

**Summary:**
• Best Bid: $${bids[0]?.[0]?.toLocaleString() || 'N/A'}
• Best Ask: $${asks[0]?.[0]?.toLocaleString() || 'N/A'}
• Mark Price: $${book.mark_price?.toLocaleString() || 'N/A'}
• State: ${book.state || 'N/A'}
• Timestamp: ${new Date(book.timestamp).toISOString()}`;

        return {
          content: [{
            type: 'text',
            text: formatted
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error fetching order book: ${error.message}`
          }]
        };
      }
    }
  );

  // ========================================
  // NEW TOOLS - ADDITIONAL METRICS
  // ========================================

  // Tool 4: Get Index Price
  server.tool(
    'get_index_price',
    'Get the current index price for a currency (underlying spot price used for derivatives)',
    {
      index_name: z.string().describe('Index name (e.g., btc_usd, eth_usd, sol_usd)')
    },
    async ({ index_name }) => {
      try {
        const url = `${DERIBIT_API_BASE}/public/get_index_price?index_name=${index_name}`;
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
          return {
            content: [{
              type: 'text',
              text: `Error: ${data.error.message}`
            }]
          };
        }

        const result = data.result;
        const formatted = `📈 **${index_name.toUpperCase()}** Index Price:

**Current Index Price:** $${result.index_price?.toLocaleString() || 'N/A'}
**Estimated Delivery Price:** $${result.estimated_delivery_price?.toLocaleString() || 'N/A'}

This is the reference price used for mark price calculations and settlements.`;

        return {
          content: [{
            type: 'text',
            text: formatted
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error fetching index price: ${error.message}`
          }]
        };
      }
    }
  );

  // Tool 5: Get Funding Rate
  server.tool(
    'get_funding_rate',
    'Get current and historical funding rate for perpetual contracts',
    {
      instrument_name: z.string().describe('Instrument name (e.g., BTC-PERPETUAL, ETH-PERPETUAL)'),
      start_timestamp: z.number().optional().describe('Start timestamp in ms (for historical data)'),
      end_timestamp: z.number().optional().describe('End timestamp in ms (for historical data)')
    },
    async ({ instrument_name, start_timestamp, end_timestamp }) => {
      try {
        let url = `${DERIBIT_API_BASE}/public/get_funding_rate_value?instrument_name=${instrument_name}`;
        if (start_timestamp) url += `&start_timestamp=${start_timestamp}`;
        if (end_timestamp) url += `&end_timestamp=${end_timestamp}`;
        
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
          return {
            content: [{
              type: 'text',
              text: `Error: ${data.error.message}`
            }]
          };
        }

        const result = data.result;
        const formatted = `💰 **${instrument_name}** Funding Rate:

**Current Funding Rate:** ${(result * 100).toFixed(4)}%
**8h Rate:** ${(result * 100).toFixed(4)}%
**Daily Rate (annualized):** ${(result * 100 * 3).toFixed(4)}%
**Annual Rate (est.):** ${(result * 100 * 3 * 365).toFixed(2)}%

${result > 0 ? '📊 Longs pay shorts' : '📊 Shorts pay longs'}
**Timestamp:** ${new Date().toISOString()}`;

        return {
          content: [{
            type: 'text',
            text: formatted
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error fetching funding rate: ${error.message}`
          }]
        };
      }
    }
  );

  // Tool 6: Get Historical Volatility
  server.tool(
    'get_historical_volatility',
    'Get historical volatility for a currency',
    {
      currency: z.string().describe('Currency symbol (BTC, ETH, SOL, etc.)')
    },
    async ({ currency }) => {
      try {
        const url = `${DERIBIT_API_BASE}/public/get_historical_volatility?currency=${currency}`;
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
          return {
            content: [{
              type: 'text',
              text: `Error: ${data.error.message}`
            }]
          };
        }

        const volatilities = data.result;
        const latest = volatilities[volatilities.length - 1];
        
        const formatted = `📉 **${currency}** Historical Volatility:

**Latest 30-Day Realized Volatility:** ${latest?.[1]?.toFixed(2)}%
**Timestamp:** ${new Date(latest?.[0]).toISOString()}

**Recent Volatility Data (Last 5 periods):**
${volatilities.slice(-5).map(([timestamp, vol]) => 
  `• ${new Date(timestamp).toLocaleDateString()}: ${vol.toFixed(2)}%`
).join('\n')}

This represents the actual historical price volatility over rolling 30-day periods.`;

        return {
          content: [{
            type: 'text',
            text: formatted
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error fetching historical volatility: ${error.message}`
          }]
        };
      }
    }
  );

  // Tool 7: Get Volatility Index (DVOL)
  server.tool(
    'get_volatility_index',
    'Get the Deribit Volatility Index (DVOL) - similar to VIX for stocks',
    {
      currency: z.string().describe('Currency symbol (BTC, ETH)')
    },
    async ({ currency }) => {
      try {
        const url = `${DERIBIT_API_BASE}/public/get_volatility_index_data?currency=${currency}&resolution=1D`;
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
          return {
            content: [{
              type: 'text',
              text: `Error: ${data.error.message}`
            }]
          };
        }

        const result = data.result;
        const latest = result.data[result.data.length - 1];
        
        const formatted = `📊 **${currency}VOL** - Deribit Volatility Index:

**Current DVOL:** ${latest?.close?.toFixed(2)}%
**High:** ${latest?.high?.toFixed(2)}%
**Low:** ${latest?.low?.toFixed(2)}%
**Open:** ${latest?.open?.toFixed(2)}%

**Recent Trend (Last 5 days):**
${result.data.slice(-5).map(d => 
  `• ${new Date(d.timestamp).toLocaleDateString()}: ${d.close?.toFixed(2)}%`
).join('\n')}

DVOL measures expected 30-day volatility derived from option prices (similar to VIX).
Higher values indicate higher expected volatility.`;

        return {
          content: [{
            type: 'text',
            text: formatted
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error fetching volatility index: ${error.message}`
          }]
        };
      }
    }
  );

  // Tool 8: Get Mark Price History
  server.tool(
    'get_mark_price_history',
    'Get historical mark prices for an instrument',
    {
      instrument_name: z.string().describe('Instrument name (e.g., BTC-PERPETUAL)'),
      start_timestamp: z.number().optional().describe('Start timestamp in ms'),
      end_timestamp: z.number().optional().describe('End timestamp in ms')
    },
    async ({ instrument_name, start_timestamp, end_timestamp }) => {
      try {
        let url = `${DERIBIT_API_BASE}/public/get_mark_price_history?instrument_name=${instrument_name}`;
        if (start_timestamp) url += `&start_timestamp=${start_timestamp}`;
        if (end_timestamp) url += `&end_timestamp=${end_timestamp}`;
        
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
          return {
            content: [{
              type: 'text',
              text: `Error: ${data.error.message}`
            }]
          };
        }

        const result = data.result;
        const recent = result.slice(-10);
        
        const formatted = `📍 **${instrument_name}** Mark Price History:

**Latest Mark Price:** $${recent[recent.length - 1]?.price?.toLocaleString() || 'N/A'}
**Timestamp:** ${new Date(recent[recent.length - 1]?.timestamp).toISOString()}

**Recent Mark Prices (Last 10):**
${recent.map(item => 
  `• ${new Date(item.timestamp).toLocaleTimeString()}: $${item.price?.toLocaleString()}`
).join('\n')}

Mark price is used for margin and liquidation calculations.`;

        return {
          content: [{
            type: 'text',
            text: formatted
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error fetching mark price history: ${error.message}`
          }]
        };
      }
    }
  );

  // Tool 9: Get Last Settlements
  server.tool(
    'get_last_settlements',
    'Get recent settlement, delivery and bankruptcy events',
    {
      currency: z.string().describe('Currency symbol (BTC, ETH, SOL, etc.)'),
      type: z.enum(['settlement', 'delivery', 'bankruptcy']).optional().describe('Event type filter'),
      count: z.number().optional().describe('Number of results (default: 20)')
    },
    async ({ currency, type, count = 20 }) => {
      try {
        let url = `${DERIBIT_API_BASE}/public/get_last_settlements_by_currency?currency=${currency}&count=${count}`;
        if (type) url += `&type=${type}`;
        
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
          return {
            content: [{
              type: 'text',
              text: `Error: ${data.error.message}`
            }]
          };
        }

        const settlements = data.result.settlements;
        
        const formatted = `🏁 **${currency}** Recent Settlements:

**Total Events:** ${settlements.length}

${settlements.slice(0, 10).map(s => 
  `**${s.instrument_name}** (${s.type})
  • Position: ${s.position}
  • Settlement Price: $${s.session_price_usd?.toFixed(2) || s.mark_price?.toFixed(2) || 'N/A'}
  • P&L: ${s.session_profit_loss?.toFixed(4) || 'N/A'} ${currency}
  • Time: ${new Date(s.timestamp).toLocaleString()}`
).join('\n\n')}

${settlements.length > 10 ? `\n...and ${settlements.length - 10} more events` : ''}`;

        return {
          content: [{
            type: 'text',
            text: formatted
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error fetching settlements: ${error.message}`
          }]
        };
      }
    }
  );

  // Tool 10: Get Trade Volumes
  server.tool(
    'get_trade_volumes',
    'Get trading volume statistics across all instruments or specific currency',
    {
      currency: z.string().optional().describe('Currency symbol (BTC, ETH, SOL) - leave empty for all currencies')
    },
    async ({ currency }) => {
      try {
        const url = currency 
          ? `${DERIBIT_API_BASE}/public/get_book_summary_by_currency?currency=${currency}&kind=future`
          : `${DERIBIT_API_BASE}/public/get_book_summary_by_currency?currency=BTC&kind=future`;
        
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
          return {
            content: [{
              type: 'text',
              text: `Error: ${data.error.message}`
            }]
          };
        }

        const result = data.result;
        const totalVolume = result.reduce((sum, item) => sum + (item.volume || 0), 0);
        const totalOI = result.reduce((sum, item) => sum + (item.open_interest || 0), 0);
        
        const formatted = `📊 **${currency || 'All'}** Trading Volume Statistics:

**Total 24h Volume:** ${totalVolume.toLocaleString()} contracts
**Total Open Interest:** ${totalOI.toLocaleString()} contracts

**Top Instruments by Volume:**
${result
  .sort((a, b) => (b.volume || 0) - (a.volume || 0))
  .slice(0, 10)
  .map(item => 
    `• **${item.instrument_name}**
   Volume: ${item.volume?.toLocaleString() || '0'} | OI: ${item.open_interest?.toLocaleString() || '0'}
   Price: $${item.last?.toLocaleString() || 'N/A'} | 24h Change: ${((item.price_change || 0) * 100).toFixed(2)}%`
  ).join('\n\n')}`;

        return {
          content: [{
            type: 'text',
            text: formatted
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error fetching trade volumes: ${error.message}`
          }]
        };
      }
    }
  );

  return server;
};

// Express app setup
const app = express();
app.use(express.json());

// Health check endpoint - UPDATED with new tool count
app.get('/', (req, res) => {
  res.json({
    status: 'ok',
    name: 'Deribit MCP Server',
    version: '2.0.0',
    mcp_endpoint: '/mcp',
    transport: 'streamable-http',
    sdk_version: '@modelcontextprotocol/sdk',
    available_tools: 10,
    tools: [
      'get_ticker',
      'get_instruments',
      'get_orderbook',
      'get_index_price',
      'get_funding_rate',
      'get_historical_volatility',
      'get_volatility_index',
      'get_mark_price_history',
      'get_last_settlements',
      'get_trade_volumes'
    ]
  });
});

// MCP endpoint - UNCHANGED
app.post('/mcp', async (req, res) => {
  console.log('🔵 MCP POST request received');
  console.log('Headers:', req.headers);
  console.log('Body:', JSON.stringify(req.body, null, 2));

  try {
    const server = createMcpServer();
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
    });

    res.on('close', () => {
      console.log('🔴 Connection closed');
      transport.close();
      server.close();
    });

    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);

  } catch (error) {
    console.error('❌ Error handling MCP request:', error);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: '2.0',
        error: {
          code: -32603,
          message: 'Internal server error',
          data: error.message
        },
        id: null
      });
    }
  }
});

// GET endpoint - UNCHANGED
app.get('/mcp', (req, res) => {
  console.log('ℹ️ GET request to /mcp (SSE not implemented in stateless mode)');
  res.status(200).json({
    message: 'Deribit MCP Server - POST to this endpoint for MCP communication',
    stateless: true
  });
});

// Start server
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`🚀 Deribit MCP Server v2.0 running on port ${PORT}`);
  console.log(`📡 MCP endpoint: http://localhost:${PORT}/mcp`);
  console.log(`🏥 Health check: http://localhost:${PORT}/`);
  console.log(`🔧 Total tools: 10`);
});