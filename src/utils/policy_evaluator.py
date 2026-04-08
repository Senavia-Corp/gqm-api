from typing import List, Dict, Any
import fnmatch

class PolicyEvaluator:
    """
    Evalúa políticas IAM-like (JSON) para determinar si un usuario
    tiene permiso de ejecutar una acción sobre un recurso.
    
    Document Structure Expected:
    {
      "Statement": [
        {
          "Effect": "Allow" | "Deny",
          "Action": ["job:view", "job:edit_*"],
          "Resource": ["*"]
        }
      ]
    }
    """
    
    @staticmethod
    def evaluate(policies: List[Dict[str, Any]], action: str, resource: str = "*") -> bool:
        """
        Evalúa una lista de documentos de política.
        Retorna True si la acción está permitida, de lo contrario False.
        Un Deny explícito siempre sobreescribe un Allow.
        
        Args:
            policies: Lista de diccionarios Document (desde PermissionModel).
            action: Acción requerida (ej. "job:update_financials").
            resource: Recurso afectado (ej. "job/123" o "*").
        """
        allowed = False
        
        for policy in policies:
            if not policy or not isinstance(policy, dict):
                continue
                
            statements = policy.get("Statement", [])
            for statement in statements:
                effect = statement.get("Effect")
                actions_in_statement = statement.get("Action", [])
                resources_in_statement = statement.get("Resource", ["*"])
                
                # Check si el action hace match (soporta wildcard ej: job:*)
                action_match = any(fnmatch.fnmatchcase(action, a) for a in actions_in_statement)
                
                # Check si el resource hace match
                resource_match = any(fnmatch.fnmatchcase(resource, r) for r in resources_in_statement)
                
                if action_match and resource_match:
                    if effect == "Deny":
                        # Un Deny explicito cancela cualquier Allow previo o futuro
                        return False 
                    elif effect == "Allow":
                        allowed = True
                        
        return allowed
