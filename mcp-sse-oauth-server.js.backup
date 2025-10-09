import express from 'express';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import fetch from 'node-fetch';

const app = express();
const PORT = process.env.PORT || 10000;

// Middleware
app.use(express.json());

// CORS middleware
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Accept, Cache-Control');
  
  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }
  next();
});

// Deribit API Configuration
const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';

// Logging
const logs = [];
const MAX_LOGS = 200;

function addLog(message) {
  const timestamp = new Date().toISOString();
  const logEntry = `[${timestamp}] ${message}`;
  logs.unshift(logEntry);
  if (logs.length > MAX_LOGS) logs.pop();
  console.log(message);
}

// Define Deribit tools
const TOOLS = [
  {
    name: 'get_ticker',
    description: 'Get ticker data for a specific instrument including price, volume, and funding rate',
    inputSchema: {
      type: 'object',
      properties: {
        instrument_name: {
          type: 'string',
          description: 'Instrument name (e.g., BTC-PERPETUAL, ETH-PERPETUAL)',
        },
      },
      required: ['instrument_name'],
    },
  },
  {
    name: 'get_instruments',
    description: 'Get all available trading instruments on Deribit',
    inputSchema: {
      type: 'object',
      properties: {
        currency: {
          type: 'string',
          description: 'Currency symbol (BTC, ETH, USDC, USDT, EURR)',
        },
        kind: {
          type: 'string',
          description: 'Instrument kind (future, option, spot)',
        },
      },
    },
  },
  {
    name: 'get_orderbook',
    description: 'Get order book data for an instrument',
    inputSchema: {
      type: 'object',
      properties: {
        instrument_name: {
          type: 'string',
          description: 'Instrument name',
        },
        depth: {
          type: 'number',
          description: 'Order book depth',
        },
      },
      required: ['instrument_name'],
    },
  },
];

// Create MCP Server
function createServer() {
  const server = new Server(
    {
      name: 'deribit-mcp-server',
      version: '1.0.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  // List tools handler
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    addLog('Tools list requested');
    return {
      tools: TOOLS,
    };
  });

  // Call tool handler
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    addLog(`Tool called: ${name} with args: ${JSON.stringify(args)}`);

    try {
      let endpoint = '';
      const params = args || {};

      switch (name) {
        case 'get_ticker':
          endpoint = '/public/ticker';
          break;
        case 'get_instruments':
          endpoint = '/public/get_instruments';
          break;
        case 'get_orderbook':
          endpoint = '/public/get_order_book';
          break;
        default:
          throw new Error(`Unknown tool: ${name}`);
      }

      const url = new URL(`${DERIBIT_API_BASE}${endpoint}`);
      Object.keys(params).forEach(key => {
        if (params[key] !== undefined && params[key] !== null) {
          url.searchParams.append(key, String(params[key]));
        }
      });

      addLog(`Calling Deribit API: ${url.toString()}`);
      const response = await fetch(url.toString());
      const data = await response.json();

      if (data.error) {
        throw new Error(data.error.message);
      }

      addLog(`Tool ${name} executed successfully`);
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(data.result, null, 2),
          },
        ],
      };
    } catch (error) {
      addLog(`Tool ${name} error: ${error.message}`);
      return {
        content: [
          {
            type: 'text',
            text: `Error: ${error.message}`,
          },
        ],
        isError: true,
      };
    }
  });

  return server;
}

// Health check endpoint
app.get('/', (req, res) => {
  addLog('Health check');
  res.json({
    status: 'ok',
    name: 'Deribit MCP Server',
    version: '1.0.0',
    transport: 'sse',
    available_tools: TOOLS.length,
  });
});

// Logs endpoint
app.get('/logs', (req, res) => {
  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache');
  const logsText = logs.length > 0 ? logs.join('\n\n') : 'No logs yet';
  res.send(`=== DERIBIT MCP SERVER LOGS ===\n\n${logsText}\n\n=== END OF LOGS ===`);
});

// Main /mcp endpoint that handles SSE connection
app.get('/mcp', async (req, res) => {
  addLog('MCP SSE connection request');
  
  try {
    // Let SSEServerTransport handle all headers - don't set them manually
    const server = createServer();
    const transport = new SSEServerTransport('/mcp/message', res);
    
    await server.connect(transport);
    addLog('MCP server connected via SSE');

    // Keep connection alive
    req.on('close', () => {
      addLog('SSE connection closed');
    });

  } catch (error) {
    addLog(`SSE connection error: ${error.message}`);
    console.error('SSE Error:', error);
    if (!res.headersSent) {
      res.status(500).json({ error: error.message });
    }
  }
});

// Message handler for SSE
app.post('/mcp/message', express.text({ type: '*/*' }), async (req, res) => {
  addLog(`MCP message received: ${req.body}`);
  res.status(202).end();
});

// Start server
app.listen(PORT, () => {
  addLog(`Deribit MCP Server running on port ${PORT}`);
  addLog(`Health: http://localhost:${PORT}/`);
  addLog(`MCP SSE endpoint: http://localhost:${PORT}/mcp`);
  addLog(`Logs: http://localhost:${PORT}/logs`);
  addLog(`Available tools: ${TOOLS.length}`);
});