// Streamable HTTP MCP endpoint - handle both GET and POST
app.all('/mcp', async (req, res) => {
  const sessionId = req.headers['mcp-session-id'] || crypto.randomBytes(16).toString('hex');
  
  // Handle GET request - return server info or open SSE stream
  if (req.method === 'GET') {
    console.log(`MCP GET request - Health check`);
    
    // Return server capabilities
    res.json({
      status: 'ok',
      name: 'deribit-mcp-server',
      version: '1.0.0',
      transport: 'streamable-http',
      capabilities: {
        tools: {},
      },
    });
    return;
  }
  
  // Handle POST request - existing code
  if (req.method === 'POST') {
    console.log(`MCP POST request - Session: ${sessionId}`);
    console.log('Request body:', JSON.stringify(req.body, null, 2));
    
    try {
      const isInitialize = req.body?.method === 'initialize';
      
      // Get or create session
      let session = sessions.get(sessionId);
      if (!session || isInitialize) {
        const mcpServer = createMCPServer();
        
        // Create a simple transport that doesn't need SSE
        const mockTransport = {
          start: async () => {},
          close: async () => {},
          send: async (message) => {
            console.log('Server sending:', JSON.stringify(message, null, 2));
          },
        };
        
        await mcpServer.connect(mockTransport);
        
        session = { mcpServer, connected: true };
        sessions.set(sessionId, session);
        console.log(`Created new session: ${sessionId}`);
      }
      
      // Process the JSON-RPC request directly
      const request = req.body;
      let response;
      
      if (request.method === 'initialize') {
        response = {
          jsonrpc: '2.0',
          id: request.id,
          result: {
            protocolVersion: '2024-11-05',
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
        const result = await session.mcpServer._requestHandlers.get('tools/list')();
        response = {
          jsonrpc: '2.0',
          id: request.id,
          result,
        };
      } else if (request.method === 'tools/call') {
        const result = await session.mcpServer._requestHandlers.get('tools/call')(request);
        response = {
          jsonrpc: '2.0',
          id: request.id,
          result,
        };
      } else {
        response = {
          jsonrpc: '2.0',
          id: request.id,
          error: {
            code: -32601,
            message: `Method not found: ${request.method}`,
          },
        };
      }
      
      console.log('Response:', JSON.stringify(response, null, 2));
      
      res.writeHead(200, {
        'Content-Type': 'application/json',
        'Mcp-Session-Id': sessionId,
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Expose-Headers': 'Mcp-Session-Id',
      });
      
      res.end(JSON.stringify(response));
      
    } catch (error) {
      console.error('Error handling request:', error);
      res.status(500).json({
        jsonrpc: '2.0',
        id: req.body?.id,
        error: {
          code: -32603,
          message: error.message,
        },
      });
    }
    return;
  }
  
  // Handle OPTIONS for CORS
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }
  
  res.status(405).json({ error: 'Method not allowed' });
});