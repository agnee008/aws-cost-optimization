"""
s3_lifecycle_optimizer.py - Automated S3 Lifecycle Policy Generator

Analyzes S3 bucket access patterns and generates optimal lifecycle policies.

Author: Agnibes Banerjee
License: MIT
"""

import boto3
from datetime import datetime, timedelta
from collections import defaultdict
import json

class S3LifecycleOptimizer:
    """
    Analyze S3 bucket access patterns and generate cost-optimized lifecycle policies.
    """
    
    def __init__(self, bucket_name, region='eu-west-2'):
        self.bucket_name = bucket_name
        self.s3 = boto3.client('s3', region_name=region)
        self.cloudwatch = boto3.client('cloudwatch', region_name=region)
    
    def analyze_access_patterns(self, days=90):
        """
        Analyze object access patterns over specified period.
        
        Returns dict with age buckets and access frequency.
        """
        print(f"📊 Analyzing access patterns for {self.bucket_name}...")
        
        access_data = defaultdict(lambda: {'count': 0, 'size_gb': 0, 'last_accessed': None})
        
        # Get all objects with last modified date
        paginator = self.s3.get_paginator('list_objects_v2')
        
        for page in paginator.paginate(Bucket=self.bucket_name):
            if 'Contents' not in page:
                continue
                
            for obj in page['Contents']:
                key = obj['Key']
                last_modified = obj['LastModified'].replace(tzinfo=None)
                size_gb = obj['Size'] / (1024 ** 3)
                
                age_days = (datetime.utcnow() - last_modified).days
                
                # Categorize by age
                if age_days <= 30:
                    category = '0-30_days'
                elif age_days <= 90:
                    category = '30-90_days'
                elif age_days <= 180:
                    category = '90-180_days'
                elif age_days <= 365:
                    category = '180-365_days'
                else:
                    category = '365+_days'
                
                access_data[category]['count'] += 1
                access_data[category]['size_gb'] += size_gb
        
        return dict(access_data)
    
    def calculate_cost_savings(self, access_patterns):
        """
        Calculate potential savings from lifecycle policies.
        
        S3 Pricing (London region):
        - Standard: £0.023/GB/month
        - Standard-IA: £0.0125/GB/month  
        - Glacier Instant Retrieval: £0.004/GB/month
        - Glacier Flexible: £0.0036/GB/month
        - Glacier Deep Archive: £0.00099/GB/month
        """
        pricing = {
            'STANDARD': 0.023,
            'STANDARD_IA': 0.0125,
            'GLACIER_IR': 0.004,
            'GLACIER': 0.0036,
            'DEEP_ARCHIVE': 0.00099
        }
        
        total_size_gb = sum(data['size_gb'] for data in access_patterns.values())
        
        # Current cost (all in Standard)
        current_cost = total_size_gb * pricing['STANDARD']
        
        # Optimized cost with lifecycle policies
        optimized_cost = (
            access_patterns.get('0-30_days', {}).get('size_gb', 0) * pricing['STANDARD'] +
            access_patterns.get('30-90_days', {}).get('size_gb', 0) * pricing['STANDARD_IA'] +
            access_patterns.get('90-180_days', {}).get('size_gb', 0) * pricing['GLACIER_IR'] +
            access_patterns.get('180-365_days', {}).get('size_gb', 0) * pricing['GLACIER'] +
            access_patterns.get('365+_days', {}).get('size_gb', 0) * pricing['DEEP_ARCHIVE']
        )
        
        monthly_savings = current_cost - optimized_cost
        annual_savings = monthly_savings * 12
        savings_pct = (monthly_savings / current_cost * 100) if current_cost > 0 else 0
        
        return {
            'total_size_gb': total_size_gb,
            'current_monthly_cost_gbp': current_cost,
            'optimized_monthly_cost_gbp': optimized_cost,
            'monthly_savings_gbp': monthly_savings,
            'annual_savings_gbp': annual_savings,
            'savings_percentage': savings_pct
        }
    
    def generate_lifecycle_policy(self, aggressive=False):
        """
        Generate S3 lifecycle policy based on best practices.
        
        Args:
            aggressive: If True, use shorter transition periods
        """
        if aggressive:
            transitions = {
                'to_ia': 14,
                'to_glacier_ir': 60,
                'to_glacier': 120,
                'to_deep_archive': 270
            }
        else:
            transitions = {
                'to_ia': 30,
                'to_glacier_ir': 90,
                'to_glacier': 180,
                'to_deep_archive': 365
            }
        
        policy = {
            'Rules': [
                {
                    'Id': 'intelligent-lifecycle-policy',
                    'Status': 'Enabled',
                    'Filter': {'Prefix': ''},
                    'Transitions': [
                        {
                            'Days': transitions['to_ia'],
                            'StorageClass': 'STANDARD_IA'
                        },
                        {
                            'Days': transitions['to_glacier_ir'],
                            'StorageClass': 'GLACIER_IR'
                        },
                        {
                            'Days': transitions['to_glacier'],
                            'StorageClass': 'GLACIER'
                        },
                        {
                            'Days': transitions['to_deep_archive'],
                            'StorageClass': 'DEEP_ARCHIVE'
                        }
                    ]
                },
                {
                    'Id': 'cleanup-incomplete-uploads',
                    'Status': 'Enabled',
                    'Filter': {'Prefix': ''},
                    'AbortIncompleteMultipartUpload': {
                        'DaysAfterInitiation': 7
                    }
                },
                {
                    'Id': 'version-lifecycle',
                    'Status': 'Enabled',
                    'Filter': {'Prefix': ''},
                    'NoncurrentVersionTransitions': [
                        {
                            'NoncurrentDays': 30,
                            'StorageClass': 'GLACIER'
                        }
                    ],
                    'NoncurrentVersionExpiration': {
                        'NoncurrentDays': 90
                    }
                }
            ]
        }
        
        return policy
    
    def apply_lifecycle_policy(self, policy, dry_run=True):
        """
        Apply lifecycle policy to bucket.
        
        Args:
            policy: Lifecycle policy dict
            dry_run: If True, only show what would be applied
        """
        if dry_run:
            print("\n📝 DRY RUN - Lifecycle policy that would be applied:")
            print(json.dumps(policy, indent=2))
            print("\nRe-run with dry_run=False to apply")
            return False
        
        try:
            self.s3.put_bucket_lifecycle_configuration(
                Bucket=self.bucket_name,
                LifecycleConfiguration=policy
            )
            print(f"✅ Lifecycle policy applied to {self.bucket_name}")
            return True
        except Exception as e:
            print(f"❌ Error applying policy: {e}")
            return False
    
    def optimize(self, aggressive=False, dry_run=True):
        """
        Complete optimization workflow:
        1. Analyze access patterns
        2. Calculate savings
        3. Generate policy
        4. Apply (if not dry run)
        """
        print(f"\n{'='*60}")
        print(f"S3 LIFECYCLE OPTIMIZATION: {self.bucket_name}")
        print(f"{'='*60}\n")
        
        # Analyze
        patterns = self.analyze_access_patterns()
        
        print("\n📊 Data Distribution:")
        print(f"{'Age Range':<20} {'Objects':<15} {'Size (GB)':<15}")
        print("-" * 50)
        for age_range, data in sorted(patterns.items()):
            print(f"{age_range:<20} {data['count']:<15,} {data['size_gb']:<15,.2f}")
        
        # Calculate savings
        savings = self.calculate_cost_savings(patterns)
        
        print(f"\n💰 Cost Analysis:")
        print(f"Total storage: {savings['total_size_gb']:,.2f} GB")
        print(f"Current cost (all Standard): £{savings['current_monthly_cost_gbp']:,.2f}/month")
        print(f"Optimized cost: £{savings['optimized_monthly_cost_gbp']:,.2f}/month")
        print(f"Monthly savings: £{savings['monthly_savings_gbp']:,.2f}")
        print(f"Annual savings: £{savings['annual_savings_gbp']:,.2f}")
        print(f"Reduction: {savings['savings_percentage']:.1f}%")
        
        # Generate policy
        policy = self.generate_lifecycle_policy(aggressive=aggressive)
        
        # Apply
        if savings['monthly_savings_gbp'] > 100:  # Only apply if savings > £100/month
            print(f"\n💡 Recommendation: APPLY (savings > £100/month)")
            self.apply_lifecycle_policy(policy, dry_run=dry_run)
        else:
            print(f"\n⏭️  Recommendation: SKIP (savings < £100/month)")
        
        return savings


def main():
    """Example usage."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python s3_lifecycle_optimizer.py <bucket-name> [--aggressive] [--apply]")
        print("\nExample:")
        print("  python s3_lifecycle_optimizer.py my-data-bucket")
        print("  python s3_lifecycle_optimizer.py my-data-bucket --aggressive")
        print("  python s3_lifecycle_optimizer.py my-data-bucket --apply")
        sys.exit(1)
    
    bucket_name = sys.argv[1]
    aggressive = '--aggressive' in sys.argv
    apply = '--apply' in sys.argv
    
    optimizer = S3LifecycleOptimizer(bucket_name)
    optimizer.optimize(
        aggressive=aggressive,
        dry_run=not apply
    )


if __name__ == '__main__':
    main()
