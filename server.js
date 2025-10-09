import express from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';

const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';

// Create the MCP server instance
const createMcpServer = () => {
  const server = new McpServer({
    name: 'deribit-mcp-server',
    version: '1.0.0',
  });

  // Tool 1: Get Ticker Data
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
- Last Price: $${ticker.last_price?.toLocaleString() || 'N/A'}
- Mark Price: $${ticker.mark_price?.toLocaleString() || 'N/A'}
- Best Bid: $${ticker.best_bid_price?.toLocaleString() || 'N/A'}
- Best Ask: $${ticker.best_ask_price?.toLocaleString() || 'N/A'}

**Volume & Interest:**
- 24h Volume: ${ticker.stats?.volume || 'N/A'} ${ticker.underlying_index || ''}
- Open Interest: ${ticker.open_interest || 'N/A'}

**Funding (if applicable):**
- Current Rate: ${ticker.current_funding ? (ticker.current_funding * 100).toFixed(4) + '%' : 'N/A'}
- 8h Funding: ${ticker.funding_8h ? (ticker.funding_8h * 100).toFixed(4) + '%' : 'N/A'}

**Statistics:**
- 24h High: $${ticker.stats?.high || 'N/A'}
- 24h Low: $${ticker.stats?.low || 'N/A'}
- State: ${ticker.state || 'N/A'}`;

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

  // Tool 2: Get Available Instruments
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

  // Tool 3: Get Order Book
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
- Best Bid: $${bids[0]?.[0]?.toLocaleString() || 'N/A'}
- Best Ask: $${asks[0]?.[0]?.toLocaleString() || 'N/A'}
- Mark Price: $${book.mark_price?.toLocaleString() || 'N/A'}
- State: ${book.state || 'N/A'}
- Timestamp: ${new Date(book.timestamp).toISOString()}`;

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

  return server;
};

// Express app setup
const app = express();
app.use(express.json());

// Health check endpoint
app.get('/', (req, res) => {
  res.json({
    status: 'ok',
    name: 'Deribit MCP Server',
    version: '1.0.0',
    mcp_endpoint: '/mcp',
    transport: 'streamable-http',
    sdk_version: '@modelcontextprotocol/sdk',
    available_tools: 3,
    tools: [
      'get_ticker',
      'get_instruments',
      'get_orderbook'
    ]
  });
});

// MCP endpoint - handles all MCP communication
app.post('/mcp', async (req, res) => {
  console.log('🔵 MCP POST request received');
  console.log('Headers:', req.headers);
  console.log('Body:', JSON.stringify(req.body, null, 2));

  try {
    // Create new server instance for each request (stateless mode)
    const server = createMcpServer();
    
    // Create transport with no session ID (stateless)
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined, // Stateless mode
    });

    // Clean up on connection close
    res.on('close', () => {
      console.log('🔴 Connection closed');
      transport.close();
      server.close();
    });

    // Connect server to transport
    await server.connect(transport);

    // Handle the request using the SDK
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

// Optional: Support for GET requests (for SSE if needed)
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
  console.log(`🚀 Deribit MCP Server running on port ${PORT}`);
  console.log(`📡 MCP endpoint: http://localhost:${PORT}/mcp`);
  console.log(`🏥 Health check: http://localhost:${PORT}/`);
});