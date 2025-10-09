import express from 'express';
import crypto from 'crypto';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import fetch from 'node-fetch';

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Log storage for debugging
const logs = [];
const MAX_LOGS = 200;

function addLog(message) {
  const timestamp = new Date().toISOString();
  const logEntry = `[${timestamp}] ${message}`;
  logs.unshift(logEntry);
  if (logs.length > MAX_LOGS) logs.pop();
  console.log(message);
}

// Enable CORS
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept, Mcp-Session-Id');
  if (req.method === 'OPTIONS') {
    return res.sendStatus(200);
  }
  next();
});

// Deribit API Configuration
const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';

// Session storage for connected clients
const sessions = new Map();

// Define tools array globally so we can use it in multiple places
const TOOLS_LIST = [
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

// Create MCP Server instance
function createMCPServer() {
  const mcpServer = new Server(
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

  mcpServer.setRequestHandler(ListToolsRequestSchema, async () => {
    return { tools: TOOLS_LIST };
  });

  mcpServer.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;

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

      const response = await fetch(url.toString());
      const data = await response.json();

      if (data.error) {
        throw new Error(data.error.message);
      }

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(data.result, null, 2),
          },
        ],
      };
    } catch (error) {
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

  return mcpServer;
}

// Health check root
app.get('/', (req, res) => {
  addLog('GET / - Health check request');
  res.json({
    status: 'ok',
    name: 'Deribit MCP Server',
    version: '1.0.0',
    mcp_endpoint: '/mcp',
    transport: 'streamable-http',
    available_tools: TOOLS_LIST.length,
  });
});

// Logs endpoint - view live logs in browser
app.get('/logs', (req, res) => {
  addLog('GET /logs - Logs viewer accessed');
  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache');
  
  const logsText = logs.length > 0 
    ? logs.join('\n\n') 
    : 'No logs yet. Try connecting from Claude to generate logs.';
  
  res.send(`=== DERIBIT MCP SERVER LOGS ===\n\n${logsText}\n\n=== END OF LOGS ===`);
});

// Streamable HTTP MCP endpoint - handle both GET and POST
app.all('/mcp', async (req, res) => {
  const sessionId = req.headers['mcp-session-id'] || crypto.randomBytes(16).toString('hex');
  
  // Handle GET request - return server info
  if (req.method === 'GET') {
    addLog(`MCP GET request - Health check`);
    return res.json({
      status: 'ok',
      name: 'deribit-mcp-server',
      version: '1.0.0',
      transport: 'streamable-http',
      capabilities: {
        tools: {},
      },
      available_tools: TOOLS_LIST.length,
    });
  }
  
  // Handle POST request
  if (req.method === 'POST') {
    addLog(`MCP POST request - Session: ${sessionId}`);
    addLog(`Request body: ${JSON.stringify(req.body, null, 2)}`);
    
    try {
      const isInitialize = req.body?.method === 'initialize';
      
      let session = sessions.get(sessionId);
      if (!session || isInitialize) {
        const mcpServer = createMCPServer();
        
        const mockTransport = {
          start: async () => {},
          close: async () => {},
          send: async (message) => {
            addLog(`Server sending: ${JSON.stringify(message, null, 2)}`);
          },
        };
        
        await mcpServer.connect(mockTransport);
        
        session = { mcpServer, connected: true };
        sessions.set(sessionId, session);
        addLog(`Created new session: ${sessionId}`);
      }
      
      const request = req.body;
      let response;
      
      if (request.method === 'initialize') {
        response = {
          jsonrpc: '2.0',
          id: request.id,
          result: {
            protocolVersion: '2025-06-18',  // ← UPDATED TO MATCH CLAUDE
            capabilities: {
              tools: {},
            },
            serverInfo: {
              name: 'deribit-mcp-server',
              version: '1.0.0',
            },
          },
        };
      } else if (request.method === 'tools/list') {
        // Return tools list directly with proper format
        addLog(`Returning tools list with ${TOOLS_LIST.length} tools`);
        response = {
          jsonrpc: '2.0',
          id: request.id,
          result: {
            tools: TOOLS_LIST,
          },
        };
      } else if (request.method === 'tools/call') {
        const result = await session.mcpServer._requestHandlers.get('tools/call')(request);
        response = {
          jsonrpc: '2.0',
          id: request.id,
          result,
        };
      } else if (request.method && request.method.startsWith('notifications/')) {
        // Handle notifications - they don't require responses in JSON-RPC 2.0
        addLog(`Received notification: ${request.method}`);
        // Notifications don't have an id field and don't expect responses
        if (!request.id) {
          // Just acknowledge with 200 OK, no JSON-RPC response needed
          addLog('Notification handled - no response needed');
          return res.status(200).end();
        }
        // If somehow it has an id (non-standard), acknowledge it
        response = {
          jsonrpc: '2.0',
          id: request.id,
          result: {},
        };
      } else {
        addLog(`Unknown method: ${request.method}`);
        response = {
          jsonrpc: '2.0',
          id: request.id,
          error: {
            code: -32601,
            message: `Method not found: ${request.method}`,
          },
        };
      }
      
      addLog(`Response: ${JSON.stringify(response, null, 2)}`);
      
      res.writeHead(200, {
        'Content-Type': 'application/json',
        'Mcp-Session-Id': sessionId,
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Expose-Headers': 'Mcp-Session-Id',
      });
      
      return res.end(JSON.stringify(response));
      
    } catch (error) {
      addLog(`ERROR: ${error.message}`);
      addLog(`ERROR STACK: ${error.stack}`);
      console.error('Error handling request:', error);
      return res.status(500).json({
        jsonrpc: '2.0',
        id: req.body?.id,
        error: {
          code: -32603,
          message: error.message,
          data: {
            errorDetails: error.stack,
          },
        },
      });
    }
  }
  
  return res.status(405).json({ error: 'Method not allowed' });
});

app.listen(PORT, () => {
  addLog(`Deribit MCP Server (Streamable HTTP) running on port ${PORT}`);
  addLog(`MCP endpoint: http://localhost:${PORT}/mcp`);
  addLog(`Available tools: ${TOOLS_LIST.length}`);
  addLog(`Logs viewer: http://localhost:${PORT}/logs`);
});